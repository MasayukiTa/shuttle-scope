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
  /** QR/session participant identity for account-less camera devices. */
  participantId?: number | null
  participantToken?: string
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
 *   - 上限超過時は **新しいほうを捨てる**。サーバが逐次受信しか受け付けないため、
 *     既に並んでいる古い chunk を捨てると連番が途切れ、以後は何を送っても 409 に
 *     なる（＝残り全部を失う）。捨てた分は errorMsg に出す。
 *
 * リトライ間隔:
 *   - RETRY_INTERVAL_MS=15s。送信は常に 1 本だけ走る（pump）ので、
 *     回線復帰時に一斉送信して burst にはならない。
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
  const { matchId, sessionCode, participantId, participantToken, timesliceSec = DEFAULT_TIMESLICE_SEC, enabled = DEFAULT_AUTO_RECORD } = options

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

  // 送信キュー（index 昇順の FIFO）。
  //
  // サーバは streaming モードで `chunk_index != received_count` を 409 にする
  // (`uploads.py`)。**厳密に 1 本ずつ・順番どおり**でなければ受け付けない。
  // 旧実装はこれに 2 つの点で反していた:
  //
  //   1. `ondataavailable` が `void uploadChunk(...)` で投げっぱなしにしており、
  //      回線が揺れて n+1 が n より先に着くと 409。以後すべて 409 になり、
  //      そこで録画が終わる
  //   2. あふれたとき**古い順に drop** していた。逐次が前提のサーバでは、
  //      index N を捨てた時点で N+1 以降が永久に受け付けられない。
  //      「最新を残す」つもりの方針が、実際には**残り全部の損失**を確定させていた
  //
  // したがって送信は 1 本に直列化し、index は**キューに入るときに**採番する
  // (入れられなかった chunk は index を消費しない = 連番が途切れない)。
  // localStorage には絶対に書かない (R16 F-2 の DoS/XSS 経路を再導入しない)。
  const queueRef = useRef<Array<{ index: number; blob: Blob }>>([])
  const retryTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const droppedChunksRef = useRef<number[]>([])
  const sendingRef = useRef<boolean>(false)
  const fatalRef = useRef<boolean>(false)

  // ─── 送信キュー操作 ──────────────────────────────────────────────
  /**
   * chunk をキュー末尾に積む。**index はここで採番する。**
   *
   * 満杯なら**新しいほうを捨てる**。逐次が前提なので、既に並んでいる
   * 古い chunk を捨てると連番が途切れ、以後は何を送っても 409 になる。
   * 捨てた分は録画に時間の穴として残るが、**その先の録画は続けられる**。
   * 穴が空いたことは errorMsg に出す（黙って捨てない）。
   */
  const enqueue = useCallback((blob: Blob): boolean => {
    if (fatalRef.current) return false
    const q = queueRef.current
    if (q.length >= MAX_PENDING_CHUNKS) {
      droppedChunksRef.current.push(chunkIndexRef.current)
      setErrorMsg(
        `送信が追いつかず、この時点の映像を ${droppedChunksRef.current.length} 個ぶん破棄しました` +
        '（録画は継続しています。映像に欠落が残ります）',
      )
      return false
    }
    q.push({ index: chunkIndexRef.current++, blob })
    return true
  }, [])

  // ─── アップロード関数 ───────────────────────────────────────────
  const getUploadAuthHeaders = useCallback((): Record<string, string> => {
    if (participantToken && participantId != null && sessionCode) {
      return {
        Authorization: 'Participant ' + participantToken,
        'X-Session-Code': sessionCode,
        'X-Participant-Id': String(participantId),
      }
    }
    const token = sessionStorage.getItem('shuttlescope_token') ?? ''
    return token ? { Authorization: 'Bearer ' + token } : {}
  }, [participantId, participantToken, sessionCode])

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
          ...getUploadAuthHeaders(),
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
          // 5xx / 一過性。キューの先頭に残したまま次の interval で再送する
          // （pump 側が shift しないので順序は保たれる）。
          return false
        } else {
          // 4xx は再送しても解消しない。**だがこの枝はエラーを一切
          // 表示せずに return していた。**
          // 逐次モードのサーバは `chunk_index != received_count` を 409 で
          // 返すので、1 個失敗した時点で以後すべて 409 になる。つまり
          // 通信の一瞬の揺らぎで録画が途切れ、**画面は「録画中」のまま、
          // 操作者は録れていると信じ続ける**。
          // 直せない失敗こそ、黙って捨ててはいけない。
          // 4xx はこのセッションでは回復しない。再送し続けても同じ 409 を
          // 繰り返すだけなので、fatal を立てて送信を止める。
          fatalRef.current = true
          setErrorMsg(
            `アップロードが拒否されました (HTTP ${res.status})。` +
              'この時点以降の録画は保存されていません。',
          )
        }
        return false
      }
      setUploadedChunks((n) => n + 1)
      return true
    } catch (err: unknown) {
      // ネットワーク完全切断等の throw。先頭に残して次の interval で再送。
      setErrorMsg(errorMessage(err))
      return false
    }
  }, [getUploadAuthHeaders])

  // ─── 送信ポンプ（直列・順序保証） ──────────────────────────────
  /**
   * キューの先頭から 1 本ずつ送る。**同時に走るのは常に 1 本だけ。**
   *
   * サーバが `chunk_index == received_count` を要求するので、並行に投げると
   * 到着順が入れ替わった瞬間に 409 になり、そこで録画が終わる。
   * 成功したものだけを shift し、失敗したら先頭に残して打ち切る
   * （次の interval か次の chunk で再開する）。順序は決して入れ替えない。
   */
  const pump = useCallback(async () => {
    if (sendingRef.current) return
    if (fatalRef.current) return
    if (!uploadIdRef.current) return
    if (queueRef.current.length === 0) return
    sendingRef.current = true
    try {
      while (queueRef.current.length > 0) {
        if (!uploadIdRef.current || fatalRef.current) break
        const head = queueRef.current[0]
        const ok = await uploadChunk(head.blob, head.index)
        if (!ok) break          // 先頭を残したまま打ち切る = 順序が崩れない
        queueRef.current.shift()
      }
    } finally {
      sendingRef.current = false
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
      const base = apiBaseRef.current || ''
      const r = await fetch(`${base}/api/v1/uploads/video/init`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getUploadAuthHeaders(),
        },
        body: JSON.stringify({
          match_id: matchId,
          filename: `sender_record_${Date.now()}.${mimeType.includes('mp4') ? 'mp4' : 'webm'}`,
          mime_type: mimeType,
          streaming: true,
          total_size: 50_000_000_000,
          chunk_size: 8_388_608,
        }),
      })
      if (!r.ok) {
        const body = await r.text()
        throw new Error(`HTTP ${r.status}: ${body.slice(0, 160)}`)
      }
      const payload = await r.json() as ({ data?: InitResponse } & Partial<InitResponse>)
      initRes = payload.data ?? (payload as InitResponse)
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
      // 並行に投げない。キューに積んでポンプを起こすだけ。
      // （サーバは chunk_index == received_count を要求する）
      if (enqueue(e.data)) void pump()
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
    queueRef.current = []
    droppedChunksRef.current = []
    fatalRef.current = false
    sendingRef.current = false
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
    retryTimerRef.current = setInterval(() => { void pump() }, RETRY_INTERVAL_MS)
    return true
  }, [matchId, timesliceSec, enabled, enqueue, pump, getUploadAuthHeaders])

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
      queueRef.current = []
      setState('idle')
      return
    }
    // 最終 ondataavailable が出るまで少し待つ
    await new Promise((r) => setTimeout(r, 500))
    // Round 258 R17 P0 fix (NEW-1): finalize 前に pending を可能な限り flush。
    // タイマーで自然に流れるのを待つと finalize と競合するため明示的に呼ぶ。
    try { await pump() } catch { /* noop */ }
    // retry timer 停止 (finalize 後の再送は無意味)
    if (retryTimerRef.current) {
      clearInterval(retryTimerRef.current)
      retryTimerRef.current = null
    }
    // uploadId をここで無効化 → 以降の uploadChunk は no-op
    uploadIdRef.current = null
    const droppedCount = droppedChunksRef.current.length
    const stillPending = queueRef.current.length
    queueRef.current = []
    if (droppedCount > 0 || stillPending > 0) {
      setErrorMsg(
        `chunk loss: dropped=${droppedCount} stillPending=${stillPending} ` +
        `(録画は完了したが一部欠損あり)`,
      )
    }
    try {
      const base = apiBaseRef.current || ''
      const res = await fetch(`${base}/api/v1/uploads/video/${uploadId}/finalize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getUploadAuthHeaders(),
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
  }, [pump, getUploadAuthHeaders])

  // unmount で必ず停止
  useEffect(() => {
    return () => { void stop() }
  }, [stop])

  return { state, start, stop, uploadedChunks, errorMsg }
}
