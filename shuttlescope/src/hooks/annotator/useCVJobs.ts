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
  // Video overlay
  currentVideoSec: number
  videoContainerRef: RefObject<HTMLDivElement>
}

// ── フック本体 ────────────────────────────────────────────────────────────────

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

  // ── YOLO ──────────────────────────────────────────────────────────────────

  const [yoloJobId, setYoloJobId] = useState<string | null>(null)
  const [yoloJob, setYoloJob] = useState<YoloJob | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [yoloFrames, setYoloFrames] = useState<any[]>([])
  const [yoloOverlayVisible, setYoloOverlayVisible] = useState(false)
  const [yoloArtifactMeta, setYoloArtifactMeta] = useState<{
    created_at: string; frame_count: number
  } | null>(null)

  // ── ビデオオーバーレイ ────────────────────────────────────────────────────

  const [currentVideoSec, setCurrentVideoSec] = useState(0)
  const videoContainerRef = useRef<HTMLDivElement>(null)

  // ── P3: TrackNet バッチ起動 ───────────────────────────────────────────────

  const handleTracknetBatch = useCallback(async () => {
    if (!matchId) return
    const hasVideo = !!(match?.video_local_path || match?.video_url)
    if (!hasVideo) {
      alert(t('tracknet.batch_no_video'))
      return
    }
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/tracknet/batch/${matchId}`,
        { backend: tracknetBackend, confidence_threshold: 0.5, roi_rect: roiRect ?? null }
      )
      if (res.success) {
        setTracknetJobId(res.data.job_id)
        setTracknetJob({
          status: 'pending', progress: 0, processed_rallies: 0,
          total_rallies: 0, updated_strokes: 0, error: null,
        })
      }
    } catch (err: unknown) {
      // HTTP エラー（503 など）の場合、サーバーの具体的な理由を表示する
      const reason = extractApiError(err)
      setTracknetJob({
        status: 'error', progress: 0, processed_rallies: 0,
        total_rallies: 0, updated_strokes: 0, error: reason,
      })
    }
  }, [matchId, match, tracknetBackend, t, roiRect])

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

  // ── P4: YOLO バッチ起動 ───────────────────────────────────────────────────

  const handleYoloBatch = useCallback(async () => {
    if (!matchId) return
    const hasVideo = !!(match?.video_local_path || match?.video_url)
    if (!hasVideo) {
      alert(t('yolo.batch_no_video'))
      return
    }
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/yolo/batch/${matchId}`,
        { roi_rect: roiRect ?? null }
      )
      if (res.success) {
        setYoloJobId(res.data.job_id)
        setYoloJob({
          status: 'pending', progress: 0, processed_frames: 0,
          total_frames: 0, detected_players: 0, error: null,
        })
      }
    } catch (err: unknown) {
      const reason = extractApiError(err)
      setYoloJob({
        status: 'error', progress: 0, processed_frames: 0,
        total_frames: 0, detected_players: 0, error: reason,
      })
    }
  }, [matchId, match, t, roiRect])

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
    // YOLO
    yoloJobId,
    yoloJob,
    setYoloJob,
    yoloFrames,
    yoloOverlayVisible,
    setYoloOverlayVisible,
    yoloArtifactMeta,
    handleYoloBatch,
    // Video overlay
    currentVideoSec,
    videoContainerRef,
  }
}
