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
import { errorMessage } from '@/utils/errors'


// Round 258 R17 P3 fix (NEW-6) → R18 P1 (R18a NEW-9):
// R17 で正規表現化したが `[A-Za-z0-9_-]{1,128}$` は依然として偶発衝突する key を
// 巻き込む。例えば `__ss_pending_upload_user_settings` は match してしまう
// (R17 のコメントは「対象外」と書いていたが実装が一致していなかった盲点)。
// 修正: 旧フォーマットの **正確な構造** だけを許可:
//   - `__ss_pending_upload_<digits>`               (R15 以前)
//   - `__ss_pending_upload_<uploadId-hex>_<digits>` (R16 fd69298 以前)
// 偶発的に同 prefix を使う将来の legitimate key (例: `_user_settings`) は
// 両パターンに該当せず、sweep されない。
const _STALE_UPLOAD_KEY_RE =
  /^__ss_pending_upload_(?:\d{1,12}|[0-9a-fA-F-]{32,40}_\d{1,12})$/

// Round 258 R20 P3 fix (R18a-1 P3-1): 同じ hook が複数 mount された場合に
// useEffect から呼ばれて何度も全 localStorage を走査するのは無駄。module-level
// flag でプロセス内 1 回だけ走査する。
let _didSweepStaleUploadQueue = false

function _sweepStaleUploadQueue(): void {
  // Round 258 R16 P0 fix (deep audit F-2): 旧バージョンが localStorage に
  // base64 化した chunk を残している場合、起動時に削除する。
  if (_didSweepStaleUploadQueue) return
  _didSweepStaleUploadQueue = true
  try {
    const keysToRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && _STALE_UPLOAD_KEY_RE.test(k)) keysToRemove.push(k)
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

/**
 * Round 258 R17 P0 fix (regression of R16 F-2 NEW-1):
 *   R16 で localStorage retry を全削除した結果、ネットワーク 5xx / 切断時の chunk が
 *   そのまま捨てられ、試合映像に永続的な穴が空く重大データ損失となっていた。
 *   修正: メモリ上に bounded pending Map を持ち、retry timer で再送する。
 *   localStorage には**書かない** (F-2 の DoS / XSS 経路を再導入しない)。
 *
 * 容量設計:
 *   - 1 chunk = 8 MB (mediaRecorder 出力)
 *   - MAX_PENDING_CHUNKS=20 → 最大 ~160 MB の RAM。
 *     ブラウザタブの heap (1-2 GB) には十分収まり、かつ無限にバッファして
 *     OOM で renderer プロセスが落ちる事故を防ぐ。
 *   - 上限超過時は **古い順に drop**。完全な無欠録画は諦め、最新分の保全を優先。
 *     drop した chunkIndex は errorMsg に記録するので運用側が認識できる。
 *
 * リトライ間隔:
 *   - RETRY_INTERVAL_MS=15s。timeslice=10s なので「次の chunk と同時に裏で再送」され、
 *     burst にはならない (uploadChunk は並行 fire-and-forget)。
 */
const MAX_PENDING_CHUNKS = 20
const RETRY_INTERVAL_MS = 15_000


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

  // Round 258 R17 P0 fix (NEW-1): メモリ上の pending chunk キュー。
  // localStorage には絶対に書かない (R16 F-2 の DoS/XSS 経路を再導入しない)。
  // Map<chunkIndex, Blob> insertion-order を保つので「古い順に drop」が自然にできる。
  const pendingRef = useRef<Map<number, Blob>>(new Map())
  const retryTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const droppedChunksRef = useRef<number[]>([])
  const retryInFlightRef = useRef<boolean>(false)

  // ─── pending キュー操作 ──────────────────────────────────────────
  // Round 258 R17 P0 fix (NEW-1): pending Map に積む。容量超過時は古い順に drop。
  const enqueuePending = useCallback((chunkIndex: number, blob: Blob) => {
    const q = pendingRef.current
    // 既に同じ index が居る場合 (retry の再失敗) は新しい blob で上書きしない
    // (Map.set で同 key を再 set するとイテレーション順序が末尾に移動する仕様だが、
    //  blob 自体は同じなので「新しい失敗」として末尾扱いになるのは許容)。
    q.set(chunkIndex, blob)
    while (q.size > MAX_PENDING_CHUNKS) {
      const oldestKey = q.keys().next().value
      if (oldestKey === undefined) break
      q.delete(oldestKey)
      droppedChunksRef.current.push(oldestKey as number)
      setErrorMsg(
        `pending queue overflow: chunk #${oldestKey} dropped ` +
        `(total dropped: ${droppedChunksRef.current.length})`,
      )
    }
  }, [])

  // ─── アップロード関数 ───────────────────────────────────────────
  const uploadChunk = useCallback(async (blob: Blob, chunkIndex: number) => {
    // Round 258 R18 P0 fix (R18a P0-1): uploadId を **関数頭でスナップショット**。
    // 旧コードは `const uploadId = uploadIdRef.current` を取得した直後 await を挟むが、
    // その間に stop() が `uploadIdRef.current = null` を実行すると、後続の FormData は
    // 既に取得済みの古い uploadId を使う。だが retry timer 経由で再呼出された flush
    // は別の path で `uploadIdRef.current` を再読込してしまうため race の余地が残る。
    // 完全に閉じるため snapshot を 1 回だけ取り、await 後も snapshot を信頼する。
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
      // R18 P0 fix (R18a P0-1): await 後に uploadId が無効化されている場合は
      // 結果を採用しない。stop() と並走した chunk は破棄。
      if (uploadIdRef.current !== uploadId) {
        return false
      }
      if (!res.ok) {
        // Round 258 R17 P0 fix (NEW-1, regression of R16 F-2):
        // R16 で localStorage を撤去したものの retry 経路ごと消してしまったため
        // 一過性のネットワーク失敗で chunk が永久に欠落していた。
        // 修正: localStorage には書かない (R16 F-2 の DoS/XSS 経路を温存) が、
        // メモリ上の bounded pending queue に積み、retry timer で再送する。
        // 旧 localStorage stale データは _sweepStaleUploadQueue() で sweep 済み。
        //
        // 4xx (auth / validation) はリトライしても解消しないため積まない。
        // 5xx / network のみ retry 対象。
        if (res.status >= 500 && res.status < 600) {
          enqueuePending(chunkIndex, blob)
        }
        return false
      }
      // 成功時: 既に pending に居る場合は除去 (retry 成功)
      pendingRef.current.delete(chunkIndex)
      setUploadedChunks((n) => n + 1)
      return true
    } catch (err: unknown) {
      // ネットワーク完全切断等の throw は retry 対象に積む
      enqueuePending(chunkIndex, blob)
      setErrorMsg(errorMessage(err))
      return false
    }
  }, [enqueuePending])

  // ─── retry タイマー ──────────────────────────────────────────────
  // Round 258 R17 P0 fix (NEW-1): pending を順に再送する。
  // 同時実行を 1 つに制限 (retryInFlightRef) して、回線復活直後に
  // 全 pending chunk を一斉に同時 POST し DoS 状態にしないようにする。
  const flushPending = useCallback(async () => {
    if (retryInFlightRef.current) return
    if (!uploadIdRef.current) return
    if (pendingRef.current.size === 0) return
    retryInFlightRef.current = true
    try {
      // Map のスナップショットを取って while でひとつずつ処理
      // (uploadChunk 成功時に pendingRef.current.delete されるので、
      //  同時に新たな失敗 chunk が積まれてもイテレーターは壊れない)
      const entries = Array.from(pendingRef.current.entries())
      for (const [idx, blob] of entries) {
        if (!uploadIdRef.current) break
        const ok = await uploadChunk(blob, idx)
        if (!ok) {
          // この round はここで打ち切り。次の interval まで待つ。
          break
        }
      }
    } finally {
      retryInFlightRef.current = false
    }
  }, [uploadChunk])

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
      initRes = (r as { data?: InitResponse }).data ?? (r as InitResponse)
      uploadIdRef.current = initRes.upload_id
      chunkIndexRef.current = 0
    } catch (err: unknown) {
      setErrorMsg(`init 失敗: ${errorMessage(err)}`)
      setState('error')
      return false
    }

    // MediaRecorder 起動
    let recorder: MediaRecorder
    try {
      recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4_000_000 })
    } catch (err: unknown) {
      setErrorMsg(`MediaRecorder 起動失敗: ${errorMessage(err)}`)
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
    recorder.onerror = (e: Event) => {
      const err = (e as Event & { error?: unknown }).error
      setErrorMsg(`MediaRecorder エラー: ${err != null ? String(err) : 'unknown'}`)
      setState('error')
    }
    recorder.onstop = () => {
      setState('stopping')
    }

    // Round 258 R18 P2 fix (R18a P2-4): retry timer は recorder.start() **成功後**
     // にだけ起動する。旧コードは start 前に setInterval を仕込み、recorder.start()
     // が throw した場合 timer が orphan して uploadIdRef を見ながら無駄 retry を
     // 続け、refresh されたトークンで finalize 後の session に書き込む経路まであった。
    pendingRef.current.clear()
    droppedChunksRef.current = []
    try {
      recorder.start(timesliceSec * 1000)
    } catch (err: unknown) {
      setErrorMsg(`recorder.start 失敗: ${errorMessage(err)}`)
      setState('error')
      return false
    }
    setState('recording')
    if (retryTimerRef.current) {
      clearInterval(retryTimerRef.current)
    }
    retryTimerRef.current = setInterval(() => { void flushPending() }, RETRY_INTERVAL_MS)
    return true
  }, [matchId, timesliceSec, enabled, uploadChunk, flushPending])

  // ─── 停止 + finalize ────────────────────────────────────────────
  const stop = useCallback(async () => {
    const recorder = recorderRef.current
    const uploadId = uploadIdRef.current
    recorderRef.current = null
    // uploadId は finalize 後に消す (retry に使うため)

    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch { /* noop */ }
    }
    if (!uploadId) {
      uploadIdRef.current = null
      // Round 258 R17 P0 fix (NEW-1): retry timer / pending を解放
      if (retryTimerRef.current) {
        clearInterval(retryTimerRef.current)
        retryTimerRef.current = null
      }
      pendingRef.current.clear()
      setState('idle')
      return
    }
    // 最終 ondataavailable が出るまで少し待つ
    await new Promise((r) => setTimeout(r, 500))
    // Round 258 R17 P0 fix (NEW-1): finalize 前に pending を可能な限り flush。
    // タイマーで自然に流れるのを待つと finalize と競合するため明示的に呼ぶ。
    try { await flushPending() } catch { /* noop */ }
    // retry timer 停止 (finalize 後の再送は無意味)
    if (retryTimerRef.current) {
      clearInterval(retryTimerRef.current)
      retryTimerRef.current = null
    }
    // uploadId をここで無効化 → 以降の uploadChunk は no-op
    uploadIdRef.current = null
    const droppedCount = droppedChunksRef.current.length
    const stillPending = pendingRef.current.size
    pendingRef.current.clear()
    if (droppedCount > 0 || stillPending > 0) {
      setErrorMsg(
        `chunk loss: dropped=${droppedCount} stillPending=${stillPending} ` +
        `(録画は完了したが一部欠損あり)`,
      )
    }
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
    } catch (err: unknown) {
      setErrorMsg(`finalize エラー: ${errorMessage(err)}`)
      setState('error')
    }
  }, [flushPending])

  // unmount で必ず停止
  useEffect(() => {
    return () => { void stop() }
  }, [stop])

  return { state, start, stop, uploadedChunks, errorMsg }
}
