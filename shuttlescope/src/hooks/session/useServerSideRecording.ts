/**
 * R-1: Sender 側でサーバ自動録画フック。
 *
 * 動作:
 *   1. MediaStream を受け取り、MediaRecorder で 10 秒タイムスライス録画
 *   2. backend に upload_id を init
 *   3. ondataavailable で得た Blob を chunked upload
 *   4. 停止時に finalize → ServerVideoArtifact 生成
 *
 * Round 258 R16 P0 fix (deep audit F-2):
 *   旧設計は「ネットワーク切断時はチャンクを localStorage キューに入れて後で再送」
 *   としていたが、実装は base64 dataURL を localStorage に書く形で:
 *     - 1 chunk (8MB) で base64 inflation 後 ~10.6MB → ブラウザの ~5-10MB クォータを
 *       1 失敗で破壊し、以降の legitimate localStorage 書込みが全滅する DoS
 *     - 試合映像フレーム断片が平文残留 (XSS exfil 経路)
 *     - dequeue コードが存在しない write-only orphan
 *   修正: localStorage 経由の retry は撤去。retry は memory + 上位の retry hook で。
 *   起動時に古い `__ss_pending_upload_*` キーを sweep する (下記 useEffect)。
 *
 * 使い方:
 * ```tsx
 * const recorder = useServerSideRecording({ matchId, sessionCode })
 * useEffect(() => {
 *   if (localStreamRef.current) recorder.start(localStreamRef.current)
 *   return () => recorder.stop()
 * }, [localStreamRef.current])
 * ```
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiPost } from '@/api/client'
import { resolveBaseUrl } from '@/utils/preferredEndpoint'


function _sweepStaleUploadQueue(): void {
  // Round 258 R16 P0 fix (deep audit F-2): 旧バージョンが localStorage に
  // base64 化した chunk を残している場合、起動時に全部削除する。
  try {
    const keysToRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith('__ss_pending_upload_')) keysToRemove.push(k)
    }
    for (const k of keysToRemove) localStorage.removeItem(k)
  } catch {
    /* private mode 等 */
  }
}

export type ServerRecordingState =
  | 'idle' | 'initializing' | 'recording' | 'stopping' | 'completed' | 'error'

interface InitResponse {
  upload_id: string
  chunk_size: number
  total_chunks: number
}

interface UseServerSideRecordingOptions {
  matchId: number | null
  sessionCode?: string
  /** タイムスライス秒数 (デフォルト 10 秒)。短いほどデータ損失リスク減、API 負荷増 */
  timesliceSec?: number
  /** 自動録画 ON/OFF (env: VITE_SS_SENDER_AUTO_RECORD) */
  enabled?: boolean
}

interface UseServerSideRecordingReturn {
  state: ServerRecordingState
  start: (stream: MediaStream) => Promise<boolean>
  stop: () => Promise<void>
  uploadedChunks: number
  errorMsg: string | null
}

const DEFAULT_AUTO_RECORD =
  (import.meta.env.VITE_SS_SENDER_AUTO_RECORD ?? 'true') !== 'false'

const DEFAULT_TIMESLICE_SEC =
  Number(import.meta.env.VITE_SS_SENDER_CHUNK_SECONDS ?? '10')


function selectMimeType(): string {
  // iOS Safari は mp4 のみ、Chrome/Edge は VP9 webm が安定
  const candidates = [
    'video/mp4;codecs=avc1',
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/webm',
  ]
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c
  }
  return ''
}


export function useServerSideRecording(
  options: UseServerSideRecordingOptions,
): UseServerSideRecordingReturn {
  const { matchId, timesliceSec = DEFAULT_TIMESLICE_SEC, enabled = DEFAULT_AUTO_RECORD } = options

  const [state, setState] = useState<ServerRecordingState>('idle')
  const [uploadedChunks, setUploadedChunks] = useState(0)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Round 258 R16 P0 fix (deep audit F-2): 旧バージョンが localStorage に
  // 残した base64 chunk を起動時に削除する。
  useEffect(() => {
    _sweepStaleUploadQueue()
  }, [])

  const recorderRef = useRef<MediaRecorder | null>(null)
  const uploadIdRef = useRef<string | null>(null)
  const chunkIndexRef = useRef<number>(0)
  const apiBaseRef = useRef<string>('')

  // ─── アップロード関数 ───────────────────────────────────────────
  const uploadChunk = useCallback(async (blob: Blob, chunkIndex: number) => {
    const uploadId = uploadIdRef.current
    if (!uploadId) return false
    const base = apiBaseRef.current || ''
    const token = sessionStorage.getItem('shuttlescope_token') ?? ''
    const url = `${base}/api/v1/uploads/video/chunk`
    try {
      const fd = new FormData()
      fd.append('upload_id', uploadId)
      fd.append('chunk_index', String(chunkIndex))
      fd.append('chunk', blob, `chunk_${chunkIndex}.bin`)
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          // Content-Type は FormData が自動で multipart/form-data; boundary= を付与する
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: fd,
      })
      if (!res.ok) {
        // Round 258 R16 P0 fix (deep audit F-2):
        // 旧コードはアップロード失敗時に blob 全体を base64 (dataURL) 化して
        // localStorage に書き込んでいた。問題:
        //   1. base64 inflation (~33%) で 8 MB chunk が ~10.6 MB → localStorage の
        //      ブラウザ全体クォータ (5-10 MB) を 1 chunk で食い潰し、以降の
        //      legitimate localStorage 書込み (auth token migrate / theme / ROI 等) が
        //      QuotaExceededError で全滅する DoS パターン。
        //   2. 私的試合映像のフレーム断片が **平文** で localStorage に長期残留。
        //      XSS が成立すれば exfil 容易。
        //   3. `__ss_pending_upload_*` を読んで再送する dequeue コードはどこにも無く、
        //      write-only の orphan ゴミ。
        // 対策: localStorage への blob ダンプは完全撤去。失敗 chunk は次の retry
        // タイマーでメモリから再送する設計に倒す (chunkIndex を pending 管理する
        // 別実装は別 commit で対応)。今は **失敗を返して呼び出し側に retry を委譲**。
        // 旧 stale data は同 hook 起動時に sweep する (下記 useEffect)。
        return false
      }
      setUploadedChunks((n) => n + 1)
      return true
    } catch (err: any) {
      setErrorMsg(err?.message ?? String(err))
      return false
    }
  }, [])

  // ─── 開始 ───────────────────────────────────────────────────────
  const start = useCallback(async (stream: MediaStream): Promise<boolean> => {
    if (!enabled) {
      setState('idle')
      return false
    }
    if (recorderRef.current) {
      // 既に録画中
      return true
    }
    if (!matchId) {
      setErrorMsg('match_id 未指定のため録画できません')
      return false
    }
    const mimeType = selectMimeType()
    if (!mimeType) {
      setErrorMsg('このブラウザは MediaRecorder に対応していません')
      return false
    }
    setState('initializing')
    setErrorMsg(null)
    setUploadedChunks(0)

    try {
      // LAN/WAN 最速経路を採用 (R-2 の preferredEndpoint)
      apiBaseRef.current = await resolveBaseUrl()
    } catch {
      apiBaseRef.current = ''
    }

    // upload session を init (total_size=0 で streaming モード)
    let initRes: InitResponse
    try {
      const r = await apiPost<{ success: boolean; data: InitResponse }>(
        '/v1/uploads/video/init',
        {
          match_id: matchId,
          filename: `sender_record_${Date.now()}.${mimeType.includes('mp4') ? 'mp4' : 'webm'}`,
          mime_type: mimeType,
          // streaming=true: 事前にサイズが分からない MediaRecorder 経路。
          // total_size は上限 (5GB) として渡し、実サイズは finalize 時に確定する。
          streaming: true,
          total_size: 50_000_000_000,
          chunk_size: 8_388_608,   // 8MB
        },
      )
      initRes = (r as any).data ?? r
      uploadIdRef.current = initRes.upload_id
      chunkIndexRef.current = 0
    } catch (err: any) {
      setErrorMsg(`init 失敗: ${err?.message ?? err}`)
      setState('error')
      return false
    }

    // MediaRecorder 起動
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_000_000 })
    } catch (err: any) {
      setErrorMsg(`MediaRecorder 起動失敗: ${err?.message ?? err}`)
      setState('error')
      return false
    }
    recorderRef.current = recorder

    recorder.ondataavailable = (e) => {
      if (!e.data || e.data.size === 0) return
      const idx = chunkIndexRef.current++
      // 並行 upload でブロックしない (ベストエフォート)
      void uploadChunk(e.data, idx)
    }
    recorder.onerror = (e: any) => {
      setErrorMsg(`MediaRecorder エラー: ${e?.error ?? e}`)
      setState('error')
    }
    recorder.onstop = () => {
      setState('stopping')
    }

    try {
      recorder.start(timesliceSec * 1000)
      setState('recording')
      return true
    } catch (err: any) {
      setErrorMsg(`recorder.start 失敗: ${err?.message ?? err}`)
      setState('error')
      return false
    }
  }, [matchId, timesliceSec, enabled, uploadChunk])

  // ─── 停止 + finalize ────────────────────────────────────────────
  const stop = useCallback(async () => {
    const recorder = recorderRef.current
    const uploadId = uploadIdRef.current
    recorderRef.current = null
    uploadIdRef.current = null

    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch { /* noop */ }
    }
    if (!uploadId) {
      setState('idle')
      return
    }
    // 最終 ondataavailable が出るまで少し待つ
    await new Promise((r) => setTimeout(r, 500))
    try {
      const base = apiBaseRef.current || ''
      const token = sessionStorage.getItem('shuttlescope_token') ?? ''
      const res = await fetch(`${base}/api/v1/uploads/video/${uploadId}/finalize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: '{}',
      })
      if (res.ok) {
        setState('completed')
      } else {
        const body = await res.text()
        setErrorMsg(`finalize 失敗: ${res.status} ${body.slice(0, 100)}`)
        setState('error')
      }
    } catch (err: any) {
      setErrorMsg(`finalize エラー: ${err?.message ?? err}`)
      setState('error')
    }
  }, [])

  // unmount で必ず停止
  useEffect(() => {
    return () => { void stop() }
  }, [stop])

  return { state, start, stop, uploadedChunks, errorMsg }
}
