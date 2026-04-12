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
import { apiGet, apiPost } from '@/api/client'
import type { ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'
import type { Match } from '@/types'
import type { RoiRect } from '@/components/video/RoiRectOverlay'

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
  handleYoloBatchDiff: () => Promise<void>
  /** 既存 YOLO アーティファクトが存在する（再開・差分更新ボタン表示判定用） */
  yoloArtifactExists: boolean
  /** 現在の ROI が前回 YOLO 実行時より拡張されている */
  yoloRoiExpanded: boolean
  /** 既存 TrackNet 解析結果が存在する（再開ボタン表示判定用） */
  tracknetArtifactExists: boolean
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

  // ── ビデオオーバーレイ ────────────────────────────────────────────────────

  const [currentVideoSec, setCurrentVideoSec] = useState(0)
  const videoContainerRef = useRef<HTMLDivElement>(null)

  // ── マウント時: 既存アーティファクト確認 ─────────────────────────────────

  useEffect(() => {
    if (!matchId) return
    apiGet<{ success: boolean; data: { frame_count: number } | null }>(`/yolo/results/${matchId}`)
      .then(res => setYoloArtifactExists(!!(res.success && res.data)))
      .catch(() => {})
    apiGet<{ success: boolean; data: unknown[] }>(`/tracknet/shuttle_track/${matchId}`)
      .then(res => setTracknetArtifactExists(!!(res.success && Array.isArray(res.data) && res.data.length > 0)))
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

  // ── P3: TrackNet ポーリング ───────────────────────────────────────────────

  useEffect(() => {
    if (!tracknetJobId || tracknetJob?.status === 'complete' || tracknetJob?.status === 'error') return
    const id = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: TracknetJob | null }>(
          `/tracknet/batch/${tracknetJobId}/status`
        )
        if (res.success && res.data) {
          setTracknetJob(res.data)
          if (res.data?.status === 'complete') {
            queryClient.invalidateQueries({ queryKey: ['strokes'] })
            // TrackNet 完了後にシャトル軌跡アーティファクトを取得
            try {
              const trackRes = await apiGet<{ success: boolean; data: ShuttleFrame[] }>(
                `/tracknet/shuttle_track/${matchId}`
              )
              if (trackRes.success && Array.isArray(trackRes.data) && trackRes.data.length > 0) {
                setShuttleFrames(trackRes.data)
                setTracknetArtifactExists(true)
                setTracknetArtifactAt(
                  new Date().toLocaleString('ja-JP', {
                    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
                  })
                )
              }
            } catch { /* shuttle track 取得失敗は無視 */ }
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
        setYoloJob({
          status: 'pending', progress: 0, processed_frames: 0,
          total_frames: 0, detected_players: 0, error: null,
        })
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
  const handleYoloBatchDiff = useCallback(
    () => _startYoloBatch({ prevRoi: yoloLastRoi }),
    [_startYoloBatch, yoloLastRoi]
  )

  // ── P4: YOLO ポーリング ───────────────────────────────────────────────────

  useEffect(() => {
    if (!yoloJobId || yoloJob?.status === 'complete' || yoloJob?.status === 'error') return
    const id = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: YoloJob | null }>(
          `/yolo/batch/${yoloJobId}/status`
        )
        if (res.success && res.data) {
          setYoloJob(res.data)
          if (res.data?.status === 'complete') {
            // 検出完了後にフレームデータを取得
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
                setYoloArtifactExists(true)
              }
            } catch { /* meta 取得失敗は無視 */ }
          }
        }
      } catch { /* ポーリング失敗は無視 */ }
    }, 2000)
    return () => clearInterval(id)
  }, [yoloJobId, yoloJob?.status, matchId])

  // ── P4: 動画再生位置の追跡（オーバーレイ同期） ───────────────────────────

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const onTimeUpdate = () => setCurrentVideoSec(video.currentTime)
    video.addEventListener('timeupdate', onTimeUpdate)
    return () => video.removeEventListener('timeupdate', onTimeUpdate)
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
    handleYoloBatchDiff,
    yoloArtifactExists,
    yoloRoiExpanded,
    // Video overlay
    currentVideoSec,
    videoContainerRef,
  }
}
