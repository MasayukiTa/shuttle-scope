/**
 * useCVScan — ラリー無し動画の全体走査（operator 専用）の状態・ポーリング・決定操作
 *
 * 流れ: 走査開始 → scan-status をポーリング → DONE 後に build → segments を読む →
 * 区間ごとに reject / accept / assign / adopt。
 *
 * CV は Rally を作らない。採用 (adopt) は既存ラリーの video_timestamp_* を人が押したときだけ書く。
 * このフックは operator 以外には使わない（呼び出し側の CVScanPanel がロールで門番する）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '@/api/client'

export const SCAN_POLL_INTERVAL_MS = 3000
/** ポーリングが連続で失敗したら打ち切る回数（ジョブ消失・サーバ再起動など） */
const SCAN_POLL_MAX_FAILURES = 5

export type ScanPhaseName = 'queued' | 'saving' | 'tracknet' | 'yolo' | 'done' | 'error'

export interface ScanSubStatus {
  status?: string | null
  progress?: number | null
  error?: string | null
}

export interface ScanStatus {
  job_id: string
  match_id: number
  phase: ScanPhaseName | string | null
  progress: number | null
  tracknet?: ScanSubStatus | null
  yolo?: ScanSubStatus | null
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
}

export type SegmentAction = 'reject' | 'accept' | 'assign'

export interface SegmentDecision {
  decision_id?: number
  start_sec: number | null
  end_sec: number | null
  action: SegmentAction
  rally_id: number | null
  decided_at?: string | null
  adopted?: boolean
}

export interface CVSegment {
  start_sec: number | null
  end_sec: number | null
  duration: number | null
  signal_score: number | null
  confidence_basis?: string | null
  open_ended: boolean
  open_side?: string | null
  coverage_ratio: number | null
  sample_count: number | null
  data_status: string
  latest_decision?: SegmentDecision | null
}

export type SegmentsStatus = 'ok' | 'no_segments' | 'insufficient_data'

export interface SegmentsData {
  match_id: number
  status: SegmentsStatus
  reason?: string | null
  sample_fps?: number | null
  sample_count?: number | null
  segments: CVSegment[]
  decisions: SegmentDecision[]
}

export interface RallyOption {
  id: number
  rally_num: number
  set_id: number
  video_timestamp_start?: number | null
  video_timestamp_end?: number | null
}

export interface ApiFailure {
  status: number | null
  detail: string
}

/** FastAPI の detail（文字列 / 検証エラー配列 / オブジェクト）を人が読める 1 行にする。 */
export function toApiFailure(err: unknown): ApiFailure {
  const status = (err as { status?: number } | null)?.status ?? null
  const raw = err instanceof Error ? err.message : String(err ?? '')
  try {
    const d = JSON.parse(raw)?.detail
    if (typeof d === 'string') return { status, detail: d }
    if (Array.isArray(d)) {
      return {
        status,
        detail: d
          .map((e: unknown) => {
            if (e && typeof e === 'object') {
              const o = e as { loc?: unknown; msg?: unknown; message?: unknown }
              const loc = Array.isArray(o.loc) ? o.loc.join('.') : ''
              const msg = String(o.msg ?? o.message ?? JSON.stringify(e))
              return loc ? `${loc}: ${msg}` : msg
            }
            return String(e)
          })
          .join('; '),
      }
    }
    if (d && typeof d === 'object') return { status, detail: JSON.stringify(d) }
  } catch {
    /* JSON ではない */
  }
  return { status, detail: raw }
}

/** 区間の同一性キー（バックエンドの _segment_key と同じ 3 桁丸め。None は 'n'）。 */
export function segmentKey(start: number | null | undefined, end: number | null | undefined): string {
  const f = (v: number | null | undefined) =>
    typeof v === 'number' && Number.isFinite(v) ? v.toFixed(3) : 'n'
  return `${f(start)}:${f(end)}`
}

export function isScanActive(phase: string | null | undefined): boolean {
  return phase != null && phase !== 'done' && phase !== 'error'
}

export interface CVScanResult {
  // 走査
  scanStatus: ScanStatus | null
  scanActive: boolean
  scanStarting: boolean
  scanFailure: ApiFailure | null
  startScan: () => Promise<void>
  // 候補生成
  building: boolean
  buildFailure: ApiFailure | null
  buildSegments: () => Promise<void>
  // 区間
  segmentsLoading: boolean
  segmentsFailure: ApiFailure | null
  segmentsData: SegmentsData | null
  reloadSegments: () => Promise<void>
  // ラリー選択肢（この試合の既存ラリーのみ）
  rallies: RallyOption[]
  ralliesLoading: boolean
  ralliesFailure: ApiFailure | null
  // 区間ごとの操作
  busyKey: string | null
  rowFailures: Record<string, ApiFailure>
  rowNotices: Record<string, string>
  decide: (seg: CVSegment, action: SegmentAction, rallyId?: number) => Promise<void>
  adopt: (seg: CVSegment, rallyId: number) => Promise<void>
}

/**
 * @param enabled 区間とラリー一覧の読み込みを始めてよいか（パネルを開いたときに true）。
 *   閉じたままの間は GET を出さない。走査のポーリングは開閉に関係なく続く。
 */
export function useCVScan(matchId: number, enabled: boolean = true): CVScanResult {
  const [scanJobId, setScanJobId] = useState<string | null>(null)
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null)
  const [scanStarting, setScanStarting] = useState(false)
  const [scanFailure, setScanFailure] = useState<ApiFailure | null>(null)

  const [building, setBuilding] = useState(false)
  const [buildFailure, setBuildFailure] = useState<ApiFailure | null>(null)

  const [segmentsLoading, setSegmentsLoading] = useState(false)
  const [segmentsFailure, setSegmentsFailure] = useState<ApiFailure | null>(null)
  const [segmentsData, setSegmentsData] = useState<SegmentsData | null>(null)

  const [rallies, setRallies] = useState<RallyOption[]>([])
  const [ralliesLoading, setRalliesLoading] = useState(false)
  const [ralliesFailure, setRalliesFailure] = useState<ApiFailure | null>(null)

  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [rowFailures, setRowFailures] = useState<Record<string, ApiFailure>>({})
  const [rowNotices, setRowNotices] = useState<Record<string, string>>({})

  // match 切替・アンマウント後の遅延応答が state を汚さないための世代番号
  const genRef = useRef(0)

  useEffect(() => {
    genRef.current += 1
    setScanJobId(null)
    setScanStatus(null)
    setScanFailure(null)
    setBuildFailure(null)
    setSegmentsData(null)
    setSegmentsFailure(null)
    setRowFailures({})
    setRowNotices({})
    return () => {
      genRef.current += 1
    }
  }, [matchId])

  // ── 区間 ────────────────────────────────────────────────────────────────
  const reloadSegments = useCallback(async () => {
    const gen = genRef.current
    setSegmentsLoading(true)
    setSegmentsFailure(null)
    try {
      const res = await apiGet<{ success: boolean; data: SegmentsData }>(
        `/cv-candidates/${matchId}/segments`,
      )
      if (gen !== genRef.current) return
      setSegmentsData(res.data)
    } catch (err) {
      if (gen !== genRef.current) return
      setSegmentsFailure(toApiFailure(err))
    } finally {
      if (gen === genRef.current) setSegmentsLoading(false)
    }
  }, [matchId])

  const reloadRallies = useCallback(async () => {
    const gen = genRef.current
    setRalliesLoading(true)
    setRalliesFailure(null)
    try {
      const res = await apiGet<{ success: boolean; data: RallyOption[] }>(`/rallies/match/${matchId}`)
      if (gen !== genRef.current) return
      setRallies(Array.isArray(res.data) ? res.data : [])
    } catch (err) {
      if (gen !== genRef.current) return
      setRalliesFailure(toApiFailure(err))
    } finally {
      if (gen === genRef.current) setRalliesLoading(false)
    }
  }, [matchId])

  // 開いた時点で既存の区間とラリー一覧を読む（match 切替でも読み直す）
  useEffect(() => {
    if (!enabled) return
    void reloadSegments()
    void reloadRallies()
  }, [enabled, reloadSegments, reloadRallies])

  // ── 走査 ────────────────────────────────────────────────────────────────
  const startScan = useCallback(async () => {
    const gen = genRef.current
    setScanStarting(true)
    setScanFailure(null)
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string; match_id: number } }>(
        `/cv-candidates/scan/${matchId}`,
        {},
      )
      if (gen !== genRef.current) return
      setScanJobId(res.data.job_id)
      setScanStatus({
        job_id: res.data.job_id, match_id: matchId, phase: 'queued', progress: 0,
      })
    } catch (err) {
      if (gen !== genRef.current) return
      setScanFailure(toApiFailure(err))
    } finally {
      if (gen === genRef.current) setScanStarting(false)
    }
  }, [matchId])

  const scanActive = scanStatus != null && isScanActive(scanStatus.phase)

  useEffect(() => {
    if (!scanJobId || !scanActive) return
    const gen = genRef.current
    let inFlight = false
    let failures = 0
    let stopped = false
    const tick = async () => {
      if (inFlight || stopped) return
      inFlight = true
      try {
        const res = await apiGet<{ success: boolean; data: ScanStatus }>(
          `/cv-candidates/scan-status/${scanJobId}`,
        )
        if (stopped || gen !== genRef.current) return
        failures = 0
        setScanStatus(res.data)
      } catch (err) {
        if (stopped || gen !== genRef.current) return
        failures += 1
        const f = toApiFailure(err)
        // 404 = ジョブが消えた（サーバ再起動など）。待ち続けても終わらない。
        if (f.status === 404 || failures >= SCAN_POLL_MAX_FAILURES) {
          stopped = true
          setScanFailure(f)
          setScanStatus((prev) => (prev ? { ...prev, phase: 'error', error: f.detail } : prev))
        }
      } finally {
        inFlight = false
      }
    }
    const id = setInterval(() => void tick(), SCAN_POLL_INTERVAL_MS)
    return () => {
      stopped = true
      clearInterval(id)
    }
  }, [scanJobId, scanActive])

  // ── 候補生成（既存の build）→ 区間を読み直す ───────────────────────────
  const buildSegments = useCallback(async () => {
    const gen = genRef.current
    setBuilding(true)
    setBuildFailure(null)
    try {
      await apiPost(`/cv-candidates/build/${matchId}`, {})
      if (gen !== genRef.current) return
      await reloadSegments()
    } catch (err) {
      if (gen !== genRef.current) return
      setBuildFailure(toApiFailure(err))
    } finally {
      if (gen === genRef.current) setBuilding(false)
    }
  }, [matchId, reloadSegments])

  // ── 区間ごとの操作 ──────────────────────────────────────────────────────
  const setRowFailure = (key: string, f: ApiFailure | null) =>
    setRowFailures((prev) => {
      const next = { ...prev }
      if (f) next[key] = f
      else delete next[key]
      return next
    })
  const setRowNotice = (key: string, msg: string | null) =>
    setRowNotices((prev) => {
      const next = { ...prev }
      if (msg) next[key] = msg
      else delete next[key]
      return next
    })

  const decide = useCallback(
    async (seg: CVSegment, action: SegmentAction, rallyId?: number) => {
      const key = segmentKey(seg.start_sec, seg.end_sec)
      const gen = genRef.current
      setBusyKey(key)
      setRowFailure(key, null)
      setRowNotice(key, null)
      const body: Record<string, unknown> = {
        start_sec: seg.start_sec,
        end_sec: seg.end_sec,
        action,
      }
      if (action === 'assign') body.rally_id = rallyId
      try {
        await apiPost(`/cv-candidates/${matchId}/segments/decisions`, body)
        if (gen !== genRef.current) return
        await reloadSegments()
      } catch (err) {
        if (gen !== genRef.current) return
        setRowFailure(key, toApiFailure(err))
      } finally {
        if (gen === genRef.current) setBusyKey(null)
      }
    },
    [matchId, reloadSegments],
  )

  const adopt = useCallback(
    async (seg: CVSegment, rallyId: number) => {
      if (seg.start_sec == null || seg.end_sec == null) return
      const key = segmentKey(seg.start_sec, seg.end_sec)
      const gen = genRef.current
      setBusyKey(key)
      setRowFailure(key, null)
      setRowNotice(key, null)
      try {
        await apiPost(`/cv-candidates/${matchId}/segments/adopt`, {
          start_sec: seg.start_sec,
          end_sec: seg.end_sec,
          rally_id: rallyId,
        })
        if (gen !== genRef.current) return
        setRowNotice(key, String(rallyId))
        await Promise.all([reloadSegments(), reloadRallies()])
      } catch (err) {
        if (gen !== genRef.current) return
        // 409（人が入れた時刻がある等）はサーバの文言をそのまま保持する
        setRowFailure(key, toApiFailure(err))
      } finally {
        if (gen === genRef.current) setBusyKey(null)
      }
    },
    [matchId, reloadSegments, reloadRallies],
  )

  return {
    scanStatus, scanActive, scanStarting, scanFailure, startScan,
    building, buildFailure, buildSegments,
    segmentsLoading, segmentsFailure, segmentsData, reloadSegments,
    rallies, ralliesLoading, ralliesFailure,
    busyKey, rowFailures, rowNotices, decide, adopt,
  }
}
