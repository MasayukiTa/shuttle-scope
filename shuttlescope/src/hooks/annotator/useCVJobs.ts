/**
 * useCVJobs — YOLO / TrackNet バッチ解析の状態・ポーリング・ハンドラを管理するフック
 *
 * 以下の関心を AnnotatorPage から分離する:
 *   - TrackNet バッチジョブ（起動・ポーリング・シャトル軌跡取得）
 *   - YOLO バッチジョブ（起動・ポーリング・フレーム取得・アーティファクトメタ）
 *   - 動画再生位置の追跡（オーバーレイ同期用 currentVideoSec）
 *   - videoContainerRef（オーバーレイ座標計算用）
 */
import { useState, useRef, useEffect, useCallback, RefObject } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import { apiGet, apiPost, apiDelete } from '@/api/client'
import type { ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'
import type { Match } from '@/types'
import type { RoiRect } from '@/components/video/RoiRectOverlay'
import type { TrackFrame, RawDetection } from '@/components/annotation/PlayerTrackingOverlay'

/** FastAPI HTTPException の detail フィールドを取り出す。取れなければ元のメッセージ。 */
function extractApiError(err: unknown): string {
  if (!(err instanceof Error)) return '不明なエラー'
  try {
    const parsed = JSON.parse(err.message)
    if (parsed?.detail) return String(parsed.detail)
  } catch { /* not JSON */ }
  return err.message
}

// ── 内部型 ───────────────────────────────────────────────────────────────────

export type TracknetJob = {
  status: string
  progress: number
  processed_rallies: number
  total_rallies: number
  updated_strokes: number
  error: string | null
}

export type YoloJob = {
  status: string
  progress: number
  processed_frames: number
  total_frames: number
  detected_players: number
  error: string | null
}

// ── オプション型 ──────────────────────────────────────────────────────────────

interface Options {
  matchId: string | undefined
  match: Match | undefined
  tracknetEnabled: boolean
  yoloEnabled: boolean
  tracknetBackend: string
  queryClient: QueryClient
  t: TFunction
  videoRef: RefObject<HTMLVideoElement>
  /** TrackNet / YOLO の解析対象エリア（正規化 0-1）。未設定なら動画全体 */
  roiRect?: RoiRect | null
}

// ── 公開型 ───────────────────────────────────────────────────────────────────

export interface CVJobsResult {
  // TrackNet
  tracknetJobId: string | null
  tracknetJob: TracknetJob | null
  setTracknetJob: React.Dispatch<React.SetStateAction<TracknetJob | null>>
  shuttleFrames: ShuttleFrame[]
  shuttleOverlayVisible: boolean
  setShuttleOverlayVisible: React.Dispatch<React.SetStateAction<boolean>>
  tracknetArtifactAt: string | null
  handleTracknetBatch: () => Promise<void>
  handleTracknetBatchResume: () => Promise<void>
  handleTracknetBatchStop: () => Promise<void>
  // YOLO
  yoloJobId: string | null
  yoloJob: YoloJob | null
  setYoloJob: React.Dispatch<React.SetStateAction<YoloJob | null>>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  yoloFrames: any[]
  yoloOverlayVisible: boolean
  setYoloOverlayVisible: React.Dispatch<React.SetStateAction<boolean>>
  yoloArtifactMeta: { created_at: string; frame_count: number } | null
  handleYoloBatch: () => Promise<void>
  handleYoloBatchResume: () => Promise<void>
  handleYoloBatchStop: () => Promise<void>
  handleYoloBatchDiff: () => Promise<void>
  handleYoloReset: () => Promise<void>
  /** 既存 YOLO アーティファクトが存在する（再開・差分更新ボタン表示判定用） */
  yoloArtifactExists: boolean
  /** 現在の ROI が前回 YOLO 実行時より拡張されている */
  yoloRoiExpanded: boolean
  /** 既存 TrackNet 解析結果が存在する（再開ボタン表示判定用） */
  tracknetArtifactExists: boolean
  // 選手識別トラッキング
  frameDetections: RawDetection[]
  trackFrames: TrackFrame[]
  trackingVisible: boolean
  setTrackingVisible: React.Dispatch<React.SetStateAction<boolean>>
  handleFrameDetect: (timestampSec: number) => Promise<void>
  handleAssignAndTrack: (
    seedTs: number,
    assignments: { detection_index: number; player_key: string; bbox?: [number, number, number, number] | null; hist?: number[] | null }[],
    extraSeeds?: { timestamp_sec: number; assignments: { detection_index: number; player_key: string; bbox?: [number, number, number, number] | null; hist?: number[] | null }[] }[]
  ) => Promise<void>
  frameDetectLoading: boolean
  trackingLoading: boolean
  /** フレーム検出エラー（APIエラー時の詳細メッセージ。nullなら正常） */
  frameDetectError: string | null
  /** フレーム検出デバッグ情報（検出ゼロ時の診断用） */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  frameDetectDebug: Record<string, any> | null
  // Video overlay
  currentVideoSec: number
  videoContainerRef: RefObject<HTMLDivElement>
}

// ── フック本体 ────────────────────────────────────────────────────────────────

/** 前回実行時の ROI より現在の ROI がいずれかの方向に拡張されているか判定 */
function roiHasExpanded(old: RoiRect | null, cur: RoiRect | null): boolean {
  if (!old || !cur) return false
  const eps = 0.001
  return (
    cur.x < old.x - eps ||
    cur.y < old.y - eps ||
    cur.x + cur.w > old.x + old.w + eps ||
    cur.y + cur.h > old.y + old.h + eps
  )
}

export function useCVJobs({
  matchId,
  match,
  tracknetBackend,
  queryClient,
  t,
  videoRef,
  roiRect,
}: Options): CVJobsResult {

  // ── TrackNet ──────────────────────────────────────────────────────────────

  const [tracknetJobId, setTracknetJobId] = useState<string | null>(null)
  const [tracknetJob, setTracknetJob] = useState<TracknetJob | null>(null)
  const [shuttleFrames, setShuttleFrames] = useState<ShuttleFrame[]>([])
  const [shuttleOverlayVisible, setShuttleOverlayVisible] = useState(false)
  const [tracknetArtifactAt, setTracknetArtifactAt] = useState<string | null>(null)
  const [tracknetArtifactExists, setTracknetArtifactExists] = useState(false)

  // ── YOLO ──────────────────────────────────────────────────────────────────

  const [yoloJobId, setYoloJobId] = useState<string | null>(null)
  const [yoloJob, setYoloJob] = useState<YoloJob | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [yoloFrames, setYoloFrames] = useState<any[]>([])
  const [yoloOverlayVisible, setYoloOverlayVisible] = useState(false)
  const [yoloArtifactMeta, setYoloArtifactMeta] = useState<{
    created_at: string; frame_count: number
  } | null>(null)
  const [yoloArtifactExists, setYoloArtifactExists] = useState(false)

  // 前回実行時の ROI（localStorage per matchId）
  const [yoloLastRoi, setYoloLastRoi] = useState<RoiRect | null>(() => {
    if (!matchId) return null
    try { return JSON.parse(localStorage.getItem(`yolo-last-roi-${matchId}`) ?? 'null') } catch { return null }
  })
  const [tracknetLastRoi, setTracknetLastRoi] = useState<RoiRect | null>(() => {
    if (!matchId) return null
    try { return JSON.parse(localStorage.getItem(`tracknet-last-roi-${matchId}`) ?? 'null') } catch { return null }
  })

  const yoloRoiExpanded = roiHasExpanded(yoloLastRoi, roiRect ?? null)

  // ── 選手識別トラッキング ──────────────────────────────────────────────────

  const [frameDetections, setFrameDetections] = useState<RawDetection[]>([])
  const [trackFrames, setTrackFrames] = useState<TrackFrame[]>([])
  const [trackingVisible, setTrackingVisible] = useState(false)
  const [frameDetectLoading, setFrameDetectLoading] = useState(false)
  const [trackingLoading, setTrackingLoading] = useState(false)
  const [frameDetectError, setFrameDetectError] = useState<string | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [frameDetectDebug, setFrameDetectDebug] = useState<Record<string, any> | null>(null)

  const handleFrameDetect = useCallback(async (timestampSec: number) => {
    if (!matchId) return
    setFrameDetectLoading(true)
    setFrameDetectError(null)
    setFrameDetectDebug(null)
    try {
      const res = await apiPost<{
        success: boolean
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data: { players: RawDetection[]; debug?: Record<string, any> }
      }>(
        `/yolo/frame_detect/${matchId}`,
        { timestamp_sec: timestampSec, roi_rect: roiRect ?? null }
      )
      if (res.success) {
        setFrameDetections(res.data.players)
        if (res.data.debug) setFrameDetectDebug(res.data.debug)
      }
    } catch (err: unknown) {
      // APIエラー詳細を保存してユーザーに表示する
      let reason = '検出APIエラー'
      if (err instanceof Error) {
        try {
          const parsed = JSON.parse(err.message)
          if (parsed?.detail) reason = String(parsed.detail)
          else reason = err.message
        } catch {
          reason = err.message
        }
      }
      setFrameDetectError(reason)
      setFrameDetections([])
    } finally {
      setFrameDetectLoading(false)
    }
  }, [matchId, roiRect])

  const handleAssignAndTrack = useCallback(async (
    seedTs: number,
    assignments: { detection_index: number; player_key: string; bbox?: [number, number, number, number] | null; hist?: number[] | null }[],
    extraSeeds?: { timestamp_sec: number; assignments: { detection_index: number; player_key: string; bbox?: [number, number, number, number] | null; hist?: number[] | null }[] }[]
  ) => {
    if (!matchId) return
    setTrackingLoading(true)
    try {
      await apiPost(`/yolo/assign_and_track/${matchId}`, {
        seed_timestamp_sec: seedTs,
        assignments,
        extra_seeds: extraSeeds ?? [],
        // コート ROI を送って、追跡時にコート外候補（観客等）を reject する
        court_roi: roiRect ?? null,
      })
      // 保存後すぐ取得
      const res = await apiGet<{ success: boolean; data: TrackFrame[] }>(
        `/yolo/identity_track/${matchId}`
      )
      if (res.success && res.data.length > 0) {
        setTrackFrames(res.data)
      }
      // 識別確定後は常にトラック表示ON（データがなくても表示状態にしておく）
      setTrackingVisible(true)
      // 移動距離カードのキャッシュを無効化して即時再取得
      queryClient.invalidateQueries({ queryKey: ['movement-stats', matchId] })
    } catch { /* 追跡失敗は無視 */ } finally {
      setTrackingLoading(false)
    }
  }, [matchId, queryClient, roiRect])

  // マウント時: 保存済みトラックを取得
  useEffect(() => {
    if (!matchId) return
    apiGet<{ success: boolean; data: TrackFrame[] }>(`/yolo/identity_track/${matchId}`)
      .then(res => { if (res.success && res.data.length > 0) setTrackFrames(res.data) })
      .catch(() => {})
  }, [matchId])

  // マウント時: YOLO モデルをバックグラウンドでウォームアップ（初回検出遅延の解消）
  useEffect(() => {
    apiPost('/yolo/warmup', {}).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── ビデオオーバーレイ ────────────────────────────────────────────────────

  const [currentVideoSec, setCurrentVideoSec] = useState(0)
  const videoContainerRef = useRef<HTMLDivElement>(null)

  // ── マウント時: 既存アーティファクト確認 ─────────────────────────────────

  useEffect(() => {
    if (!matchId) return
    apiGet<{ success: boolean; data: { frame_count: number } | null }>(`/yolo/results/${matchId}`)
      .then(res => setYoloArtifactExists(!!(res.success && res.data)))
      .catch(() => {})
    // shuttle_track を優先確認。なければ tracknet_resume_check（ストロークに land_zone が
    // 設定済みかどうか）で判定する。これにより旧バージョンで shuttle_track が保存されていない
    // 場合でも「再開」ボタンを表示できる。
    apiGet<{ success: boolean; data: unknown[] }>(`/tracknet/shuttle_track/${matchId}`)
      .then(res => {
        if (res.success && Array.isArray(res.data) && res.data.length > 0) {
          setTracknetArtifactExists(true)
        } else {
          // shuttle_track がない場合はストロークの land_zone をフォールバックで確認
          return apiGet<{ success: boolean; data: { has_land_zone: boolean } }>(
            `/tracknet/resume_check/${matchId}`
          ).then(r => {
            if (r.success && r.data?.has_land_zone) setTracknetArtifactExists(true)
          }).catch(() => {})
        }
      })
      .catch(() => {})
  }, [matchId])

  // ── P3: TrackNet バッチ起動（内部共通ハンドラ） ──────────────────────────

  const _startTracknetBatch = useCallback(async (opts: {
    resume?: boolean
    prevRoi?: RoiRect | null
  } = {}) => {
    if (!matchId) return
    const hasVideo = !!(match?.video_local_path || match?.video_url)
    if (!hasVideo) {
      alert(t('tracknet.batch_no_video'))
      return
    }
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/tracknet/batch/${matchId}`,
        {
          backend: tracknetBackend,
          confidence_threshold: 0.5,
          roi_rect: roiRect ?? null,
          resume: opts.resume ?? false,
          prev_roi: opts.prevRoi ?? null,
        }
      )
      if (res.success) {
        setTracknetJobId(res.data.job_id)
        setTracknetJob({
          status: 'pending', progress: 0, processed_rallies: 0,
          total_rallies: 0, updated_strokes: 0, error: null,
        })
        // 使用した ROI を記憶
        if (matchId) {
          const roi = roiRect ?? null
          setTracknetLastRoi(roi)
          try { localStorage.setItem(`tracknet-last-roi-${matchId}`, JSON.stringify(roi)) } catch { }
        }
      }
    } catch (err: unknown) {
      const reason = extractApiError(err)
      setTracknetJob({
        status: 'error', progress: 0, processed_rallies: 0,
        total_rallies: 0, updated_strokes: 0, error: reason,
      })
    }
  }, [matchId, match, tracknetBackend, t, roiRect])

  const handleTracknetBatch = useCallback(() => _startTracknetBatch(), [_startTracknetBatch])
  const handleTracknetBatchResume = useCallback(
    () => _startTracknetBatch({ resume: true, prevRoi: tracknetLastRoi }),
    [_startTracknetBatch, tracknetLastRoi]
  )
  const handleTracknetBatchStop = useCallback(async () => {
    if (!tracknetJobId) return
    try {
      await apiPost(`/tracknet/batch/${tracknetJobId}/stop`, {})
      setTracknetArtifactExists(true)  // 停止後すぐに「再開」ボタンを表示
    } catch { /* 停止失敗は無視 */ }
  }, [tracknetJobId])

  // ── P3: TrackNet ポーリング ───────────────────────────────────────────────

  useEffect(() => {
    if (!tracknetJobId || tracknetJob?.status === 'complete' || tracknetJob?.status === 'error' || tracknetJob?.status === 'stopped') return
    const id = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: TracknetJob | null }>(
          `/tracknet/batch/${tracknetJobId}/status`
        )
        if (res.success && res.data) {
          setTracknetJob(res.data)
          if (res.data?.status === 'complete' || res.data?.status === 'stopped') {
            setTracknetArtifactExists(true)  // 停止・完了いずれも「再開」ボタン表示
            if (res.data?.status === 'complete') {
              queryClient.invalidateQueries({ queryKey: ['strokes'] })
              // TrackNet 完了後にシャトル軌跡アーティファクトを取得
              try {
                const trackRes = await apiGet<{ success: boolean; data: ShuttleFrame[] }>(
                  `/tracknet/shuttle_track/${matchId}`
                )
                if (trackRes.success && Array.isArray(trackRes.data) && trackRes.data.length > 0) {
                  setShuttleFrames(trackRes.data)
                  setTracknetArtifactAt(
                    new Date().toLocaleString('ja-JP', {
                      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
                    })
                  )
                }
              } catch { /* shuttle track 取得失敗は無視 */ }
            }
          }
        }
      } catch { /* ポーリング失敗は無視 */ }
    }, 2000)
    return () => clearInterval(id)
  }, [tracknetJobId, tracknetJob?.status, queryClient, matchId])

  // ── P4: YOLO バッチ起動（内部共通ハンドラ） ──────────────────────────────

  const _startYoloBatch = useCallback(async (opts: {
    resume?: boolean
    prevRoi?: RoiRect | null
  } = {}) => {
    if (!matchId) return
    const hasVideo = !!(match?.video_local_path || match?.video_url)
    if (!hasVideo) {
      alert(t('yolo.batch_no_video'))
      return
    }
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/yolo/batch/${matchId}`,
        {
          roi_rect: roiRect ?? null,
          resume: opts.resume ?? false,
          prev_roi: opts.prevRoi ?? null,
        }
      )
      if (res.success) {
        setYoloJobId(res.data.job_id)
        // resume 時は既存の進捗を引き継ぎ、0% に戻さない
        setYoloJob(prev => ({
          status: 'pending',
          progress:         opts.resume ? (prev?.progress         ?? 0) : 0,
          processed_frames: opts.resume ? (prev?.processed_frames ?? 0) : 0,
          total_frames:     opts.resume ? (prev?.total_frames     ?? 0) : 0,
          detected_players: opts.resume ? (prev?.detected_players ?? 0) : 0,
          error: null,
        }))
        // 使用した ROI を記憶
        if (matchId) {
          const roi = roiRect ?? null
          setYoloLastRoi(roi)
          try { localStorage.setItem(`yolo-last-roi-${matchId}`, JSON.stringify(roi)) } catch { }
        }
      }
    } catch (err: unknown) {
      const reason = extractApiError(err)
      setYoloJob({
        status: 'error', progress: 0, processed_frames: 0,
        total_frames: 0, detected_players: 0, error: reason,
      })
    }
  }, [matchId, match, t, roiRect])

  const handleYoloBatch = useCallback(() => _startYoloBatch(), [_startYoloBatch])
  const handleYoloBatchResume = useCallback(
    () => _startYoloBatch({ resume: true }),
    [_startYoloBatch]
  )
  const handleYoloBatchStop = useCallback(async () => {
    if (!yoloJobId) return
    try {
      await apiPost(`/yolo/batch/${yoloJobId}/stop`, {})
      setYoloArtifactExists(true)  // 停止後すぐに「再開」ボタンを表示
    } catch { /* 停止失敗は無視 */ }
  }, [yoloJobId])
  const handleYoloBatchDiff = useCallback(
    () => _startYoloBatch({ prevRoi: yoloLastRoi }),
    [_startYoloBatch, yoloLastRoi]
  )
  const handleYoloReset = useCallback(async () => {
    if (!matchId) { console.warn('[YoloReset] no matchId'); return }
    console.info('[YoloReset] start match=', matchId, 'jobId=', yoloJobId, 'status=', yoloJob?.status)
    // 進行中ジョブがあれば abort 要求（バックグラウンドの書き戻し防止）
    if (yoloJobId && yoloJob && (yoloJob.status === 'pending' || yoloJob.status === 'running')) {
      try { await apiPost(`/yolo/batch/${yoloJobId}/stop`, {}) } catch (e) { console.warn('[YoloReset] stop failed', e) }
    }
    try {
      const res = await apiDelete<{ success: boolean; data: { deleted: number } }>(`/yolo/results/${matchId}`)
      console.info('[YoloReset] delete response', res)
      setYoloJob(null)
      setYoloFrames([])
      setTrackFrames([])
      setFrameDetections([])
      setYoloArtifactExists(false)
      setYoloArtifactMeta(null)
      // 解析カード（選手移動距離・累計移動距離・ゾーン別滞在頻度等）を即時リセット
      queryClient.invalidateQueries({ queryKey: ['movement-stats', matchId] })
      queryClient.invalidateQueries({ queryKey: ['yolo-doubles-analysis', matchId] })
      queryClient.invalidateQueries({ queryKey: ['cv-candidates', matchId] })
      queryClient.invalidateQueries({ queryKey: ['cv-review-queue', matchId] })
    } catch (err) {
      const status = (err as { status?: number })?.status
      const msg = err instanceof Error ? err.message : String(err)
      console.error('[YoloReset] delete failed', status, msg)
      alert(
        `YOLO 結果の削除に失敗しました (status=${status ?? '?'}).\n` +
        `バックエンドが新しい DELETE エンドポイントを認識していない可能性があります。\n` +
        `アプリを再起動してください。\n\n詳細: ${msg}`
      )
    }
  }, [matchId, yoloJobId, yoloJob, queryClient])

  // ── P4: YOLO ポーリング ───────────────────────────────────────────────────

  useEffect(() => {
    if (!yoloJobId || yoloJob?.status === 'complete' || yoloJob?.status === 'error' || yoloJob?.status === 'stopped') return
    const id = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: YoloJob | null }>(
          `/yolo/batch/${yoloJobId}/status`
        )
        if (res.success && res.data) {
          setYoloJob(res.data)
          if (res.data?.status === 'complete' || res.data?.status === 'stopped') {
            setYoloArtifactExists(true)  // 停止・完了いずれも「再開」ボタン表示
            // フレームデータを取得（停止時も部分データを反映）
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const framesRes = await apiGet<{ success: boolean; data: any[] }>(
              `/yolo/results/${matchId}/frames`
            )
            if (framesRes.success && framesRes.data) {
              setYoloFrames(framesRes.data)
            }
            // アーティファクトメタ（作成日時・フレーム数）
            try {
              const metaRes = await apiGet<{
                success: boolean
                data: { created_at: string; frame_count: number } | null
              }>(`/yolo/results/${matchId}`)
              if (metaRes.success && metaRes.data) {
                setYoloArtifactMeta({
                  created_at: metaRes.data.created_at,
                  frame_count: metaRes.data.frame_count,
                })
              }
            } catch { /* meta 取得失敗は無視 */ }
            if (res.data?.status === 'complete') {
              // バッチ完了後、バックエンドが識別トラックを自動再適用するため
              // 移動距離カードのキャッシュを無効化して最新データを反映する
              queryClient.invalidateQueries({ queryKey: ['movement-stats', matchId] })
              // 識別トラックも再取得
              try {
                const trackRes = await apiGet<{ success: boolean; data: TrackFrame[] }>(
                  `/yolo/identity_track/${matchId}`
                )
                if (trackRes.success && trackRes.data?.length) {
                  setTrackFrames(trackRes.data)
                }
              } catch { /* トラック再取得失敗は無視 */ }
            }
          }
        }
      } catch { /* ポーリング失敗は無視 */ }
    }, 2000)
    return () => clearInterval(id)
  }, [yoloJobId, yoloJob?.status, matchId])

  // ── P4: 動画再生位置の追跡（オーバーレイ同期） ───────────────────────────
  //
  // 旧実装は `useEffect(()=>{...}, [videoRef])` で video.addEventListener していたが、
  // videoRef.current は AnnotatorVideoPane が条件付きでマウントされたり src が
  // 後から差し替わるタイミングで null だったり再生成されたりするため、
  // 「ロード時には null だったので listener が付かず、後で video が出てきても
  //  effect が再走しないので永久に無音」という致命的状態に陥っていた。
  // BBOX が「最初の静止画から動かない」現象の真因。
  //
  // requestAnimationFrame で毎フレーム videoRef.current?.currentTime を読みに行く
  // 方式に変更。video 要素の有無・差し替えに関係なく現在時刻が確実に取れる。
  // 50ms 以上の差分でのみ state 更新（無駄な再レンダー抑制）。
  useEffect(() => {
    let raf = 0
    let last = -1
    const tick = () => {
      const v = videoRef.current
      if (v && !Number.isNaN(v.currentTime)) {
        const t = v.currentTime
        if (Math.abs(t - last) > 0.05) {
          last = t
          setCurrentVideoSec(t)
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [videoRef])

  // ── 公開 ──────────────────────────────────────────────────────────────────

  return {
    // TrackNet
    tracknetJobId,
    tracknetJob,
    setTracknetJob,
    shuttleFrames,
    shuttleOverlayVisible,
    setShuttleOverlayVisible,
    tracknetArtifactAt,
    handleTracknetBatch,
    handleTracknetBatchResume,
    handleTracknetBatchStop,
    tracknetArtifactExists,
    // YOLO
    yoloJobId,
    yoloJob,
    setYoloJob,
    yoloFrames,
    yoloOverlayVisible,
    setYoloOverlayVisible,
    yoloArtifactMeta,
    handleYoloBatch,
    handleYoloBatchResume,
    handleYoloBatchStop,
    handleYoloBatchDiff,
    handleYoloReset,
    yoloArtifactExists,
    yoloRoiExpanded,
    // 選手識別トラッキング
    frameDetections,
    trackFrames,
    trackingVisible,
    setTrackingVisible,
    handleFrameDetect,
    handleAssignAndTrack,
    frameDetectLoading,
    trackingLoading,
    frameDetectError,
    frameDetectDebug,
    // Video overlay
    currentVideoSec,
    videoContainerRef,
  }
}
