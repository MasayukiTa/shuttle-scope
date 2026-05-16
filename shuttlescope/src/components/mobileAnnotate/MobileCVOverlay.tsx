/**
 * MobileCVOverlay — モバイルアノテ用 CV オーバーレイ統合 (read-only)
 *
 * desktop annotator の CourtGridOverlay / ShuttleTrackOverlay /
 * PlayerPositionOverlay を統合し、モバイル向けに編集 UI を全て排した read-only 版。
 *
 * モバイル設計理由:
 *   - キャリブレーション編集はデスクトップで実施済み前提 (annotator が前処理)
 *   - モバイル側は「自動解析結果を確認 + ストローク承認/補正」だけに集中
 *   - 1 画面に編集 UI と video controls を同居させると指 hit-target 不足になる
 *
 * 3 layer 構成:
 *   1) 18 マスコートグリッド (SVG, 4 隅 + ネット 2 点が calibrated 済みなら描画)
 *   2) シャトル直近軌跡 (canvas, ±2s 以内のフレームをフェード描画)
 *   3) プレイヤー bbox (canvas, ±1.5s 以内のフレーム)
 *
 * 可視性は親 (PlayMode) からの prop で個別 toggle。
 *
 * 描画コスト:
 *   - 30fps レンダリングはしない。video の timeupdate に同期 (~4Hz) で再描画。
 *   - canvas は dpr 補正済みで物理ピクセル使用。
 */
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost } from '@/api/client'
import { ShuttleTrackOverlay, type ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  matchId: string | number
  currentSec: number
  /** ビデオ要素の表示サイズ (px)。コンテナと一致しないと座標が歪む。 */
  videoWidth: number
  videoHeight: number
  showCourt: boolean
  showShuttle: boolean
  showPlayers: boolean
}

type Pt = { x: number; y: number }

interface CourtCalibResponse {
  data?: {
    points?: [number, number][]
  }
}

interface ShuttleTrackResponse {
  success?: boolean
  data?: ShuttleFrame[]
}

interface YoloPlayerDetection {
  label: string
  confidence: number
  bbox: [number, number, number, number]
  centroid: [number, number]
  court_side: string
  depth_band: string
}

interface YoloFrame {
  frame_idx: number
  timestamp_sec: number
  players: YoloPlayerDetection[]
}

interface YoloResultsResponse {
  frames?: YoloFrame[]
}


// ─── ユーティリティ ────────────────────────────────────────────────────────

function lerp(a: Pt, b: Pt, t: number): Pt {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
}

const GRID_ROWS = 3
const GRID_COLS = 3

function halfGridLines(
  TL: Pt, TR: Pt, BR: Pt, BL: Pt,
  w: number, h: number,
): Array<{ x1: number; y1: number; x2: number; y2: number }> {
  const lines = []
  for (let r = 0; r <= GRID_ROWS; r++) {
    const v = r / GRID_ROWS
    const left = lerp(TL, BL, v)
    const right = lerp(TR, BR, v)
    lines.push({ x1: left.x * w, y1: left.y * h, x2: right.x * w, y2: right.y * h })
  }
  for (let c = 0; c <= GRID_COLS; c++) {
    const u = c / GRID_COLS
    const top = lerp(TL, TR, u)
    const bottom = lerp(BL, BR, u)
    lines.push({ x1: top.x * w, y1: top.y * h, x2: bottom.x * w, y2: bottom.y * h })
  }
  return lines
}


type CvJobStatus = {
  status: 'pending' | 'running' | 'complete' | 'error' | 'stopped'
  progress: number
  error?: string | null
  processed_rallies?: number
  total_rallies?: number
  updated_strokes?: number
  processed_frames?: number
  total_frames?: number
  detected_players?: number
} | null

export function MobileCVOverlay({
  matchId,
  currentSec,
  videoWidth,
  videoHeight,
  showCourt,
  showShuttle,
  showPlayers,
}: Props) {
  const queryClient = useQueryClient()
  // CV ジョブ進捗 (TrackNet / YOLO 共通)
  const [tracknetJobId, setTracknetJobId] = useState<string | null>(null)
  const [tracknetJob, setTracknetJob] = useState<CvJobStatus>(null)
  const [yoloJobId, setYoloJobId] = useState<string | null>(null)
  const [yoloJob, setYoloJob] = useState<CvJobStatus>(null)
  // 起動失敗時のエラー表示
  const [jobErr, setJobErr] = useState<string>('')

  const isTracknetRunning = !!tracknetJob && (tracknetJob.status === 'pending' || tracknetJob.status === 'running')
  const isYoloRunning = !!yoloJob && (yoloJob.status === 'pending' || yoloJob.status === 'running')
  const tracknetError = tracknetJob?.status === 'error' ? (tracknetJob.error || 'TrackNet 実行失敗') : null
  const yoloError = yoloJob?.status === 'error' ? (yoloJob.error || 'YOLO 実行失敗') : null
  // ジョブが complete/stopped (= 正常終了したが結果が 0 frames だったケースを含む) を
  // 「実行履歴あり」chip として残すため、別途追跡。ユーザがタップで dismiss できる。
  const tracknetCompleted = tracknetJob?.status === 'complete' || tracknetJob?.status === 'stopped'
  const yoloCompleted = yoloJob?.status === 'complete' || yoloJob?.status === 'stopped'

  // backend エラー (409 等) メッセージから既存 job_id を救出する正規表現
  const extractJobIdFromConflict = (msg: string): string | null => {
    // 例: "この試合は既に TrackNet バッチ処理中です (job_id=a60e9524)。"
    const m = msg.match(/job_id=([a-zA-Z0-9-]+)/)
    return m ? m[1] : null
  }

  const startTracknet = async () => {
    if (isTracknetRunning) return
    setJobErr('')
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/tracknet/batch/${matchId}`,
        { confidence_threshold: 0.5, resume: false, roi_rect: null, prev_roi: null },
      )
      if (res.success) {
        setTracknetJobId(res.data.job_id)
        setTracknetJob({ status: 'pending', progress: 0 })
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      // 「既に処理中」エラーから job_id を抽出して進捗を引き継ぐ
      const existing = extractJobIdFromConflict(msg)
      if (existing) {
        setTracknetJobId(existing)
        setTracknetJob({ status: 'running', progress: 0 })
        setJobErr('')  // 既存ジョブを引き継いだのでエラーは消す
      } else {
        setJobErr('TrackNet 起動失敗: ' + msg.slice(0, 200))
      }
    }
  }

  const startYolo = async () => {
    if (isYoloRunning) return
    setJobErr('')
    try {
      const res = await apiPost<{ success: boolean; data: { job_id: string } }>(
        `/yolo/batch/${matchId}`,
        { resume: false, roi_rect: null, prev_roi: null },
      )
      if (res.success) {
        setYoloJobId(res.data.job_id)
        setYoloJob({ status: 'pending', progress: 0 })
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const existing = extractJobIdFromConflict(msg)
      if (existing) {
        setYoloJobId(existing)
        setYoloJob({ status: 'running', progress: 0 })
        setJobErr('')
      } else {
        setJobErr('YOLO 起動失敗: ' + msg.slice(0, 200))
      }
    }
  }

  // TrackNet ジョブ進捗 polling (2 秒間隔)
  useEffect(() => {
    if (!tracknetJobId || !isTracknetRunning) return
    const id = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: CvJobStatus }>(
          `/tracknet/batch/${tracknetJobId}/status`,
        )
        if (res.success && res.data) {
          setTracknetJob(res.data)
          if (res.data.status === 'complete') {
            queryClient.invalidateQueries({ queryKey: ['mobile-shuttle-track', matchId] })
          }
        }
      } catch { /* keep polling */ }
    }, 2000)
    return () => clearInterval(id)
  }, [tracknetJobId, isTracknetRunning, matchId, queryClient])

  // YOLO ジョブ進捗 polling
  useEffect(() => {
    if (!yoloJobId || !isYoloRunning) return
    const id = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: CvJobStatus }>(
          `/yolo/batch/${yoloJobId}/status`,
        )
        if (res.success && res.data) {
          setYoloJob(res.data)
          if (res.data.status === 'complete') {
            queryClient.invalidateQueries({ queryKey: ['mobile-yolo-frames', matchId] })
          }
        }
      } catch { /* keep polling */ }
    }, 2000)
    return () => clearInterval(id)
  }, [yoloJobId, isYoloRunning, matchId, queryClient])
  // ─── court calibration ──────────────────────────────────────────────
  // localStorage cache を desktop と共有 (`court-calib-{id}`) するので、デスクトップで
  // キャリブレーション済みなら即座に表示される。backend 失敗時の fallback も同じ。
  const [courtPoints, setCourtPoints] = useState<Pt[]>([])

  useEffect(() => {
    if (!showCourt) return
    let cancelled = false
    apiGet<CourtCalibResponse>(`/matches/${matchId}/court_calibration`)
      .then((res) => {
        if (cancelled) return
        const raw = res?.data?.points ?? []
        if (raw.length === 6) {
          const pts = raw.map(([x, y]) => ({ x, y }))
          setCourtPoints(pts)
          try { localStorage.setItem(`court-calib-${matchId}`, JSON.stringify(pts)) } catch {}
        }
      })
      .catch(() => {
        try {
          const saved = localStorage.getItem(`court-calib-${matchId}`)
          if (saved) {
            const pts = JSON.parse(saved)
            if (Array.isArray(pts) && pts.length === 6) {
              setCourtPoints(pts)
            }
          }
        } catch {}
      })
    return () => { cancelled = true }
  }, [matchId, showCourt])

  // ─── shuttle track ──────────────────────────────────────────────────
  const shuttleQuery = useQuery({
    queryKey: ['mobile-shuttle-track', matchId],
    queryFn: () => apiGet<ShuttleTrackResponse>(`/api/tracknet/shuttle_track/${matchId}`),
    enabled: !!matchId && showShuttle,
    staleTime: 60_000,
    retry: 1,
  })
  const shuttleFrames: ShuttleFrame[] = shuttleQuery.data?.data ?? []

  // ─── player positions ──────────────────────────────────────────────
  const yoloQuery = useQuery({
    queryKey: ['mobile-yolo-frames', matchId],
    queryFn: () => apiGet<YoloResultsResponse>(`/api/yolo/results/${matchId}`),
    enabled: !!matchId && showPlayers,
    staleTime: 60_000,
    retry: 1,
  })
  const yoloFrames: YoloFrame[] = yoloQuery.data?.frames ?? []

  // ─── render ─────────────────────────────────────────────────────────

  const hasCalib = courtPoints.length === 6
  // グリッド計算
  const gridLines: Array<{ x1: number; y1: number; x2: number; y2: number; isNet?: boolean }> = []
  if (showCourt && hasCalib && videoWidth > 0 && videoHeight > 0) {
    const [TL, TR, BR, BL, NL, NR] = courtPoints
    // 上半面 (TL,TR,NR,NL)
    gridLines.push(...halfGridLines(TL, TR, NR, NL, videoWidth, videoHeight))
    // 下半面 (NL,NR,BR,BL)
    gridLines.push(...halfGridLines(NL, NR, BR, BL, videoWidth, videoHeight))
    // ネット
    gridLines.push({
      x1: NL.x * videoWidth, y1: NL.y * videoHeight,
      x2: NR.x * videoWidth, y2: NR.y * videoHeight,
      isNet: true,
    })
  }

  return (
    <>
      {/* 1) コートグリッド SVG (最背面オーバーレイ) */}
      {showCourt && hasCalib && videoWidth > 0 && videoHeight > 0 && (
        <svg
          className="absolute inset-0 pointer-events-none"
          width="100%"
          height="100%"
          style={{ zIndex: 11 }}
        >
          {gridLines.map((l, i) => (
            <g key={i}>
              <line
                x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
                stroke="#000"
                strokeWidth={l.isNet ? 4 : 3}
                strokeOpacity={0.7}
              />
              <line
                x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
                stroke={l.isNet ? '#f59e0b' : '#ffffff'}
                strokeWidth={l.isNet ? 2 : 1.2}
                strokeOpacity={1}
              />
            </g>
          ))}
        </svg>
      )}

      {/* 2) シャトル軌跡 */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ zIndex: 12 }}
      >
        <ShuttleTrackOverlay
          frames={shuttleFrames}
          currentSec={currentSec}
          videoWidth={videoWidth}
          videoHeight={videoHeight}
          visible={showShuttle && shuttleFrames.length > 0}
        />
      </div>

      {/* 3) プレイヤー bbox */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ zIndex: 13 }}
      >
        <PlayerPositionOverlay
          frames={yoloFrames}
          currentSec={currentSec}
          videoWidth={videoWidth}
          videoHeight={videoHeight}
          visible={showPlayers && yoloFrames.length > 0}
        />
      </div>

      {/* 4) データ未整備時の説明 chip → タップで CV パイプ起動。進捗も同 chip に表示。
         - コートキャリブはモバイルから編集できる (Pencil ボタン) のでこの chip は説明のみ。
         - TrackNet / YOLO はクラスタ実行になるため backend POST → 進捗ポーリング → 完了で
           react-query キャッシュ invalidate → overlay 再 fetch のフロー。 */}
      {showCourt && !hasCalib && (
        <div
          className="absolute right-2 z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-warning"
          style={{ top: 'calc(max(0.5rem, env(safe-area-inset-top)) + 2.5rem)' }}
          // chip 自体への tap が video に bubble して "セット1 prompt" を誤発火するのを防ぐ
          onClick={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
          onTouchEnd={(e) => e.stopPropagation()}
        >
          <span className="inline-flex items-center gap-1">
            コート未キャリブ (右上
            <MIcon name="edit" size={11} />
            から編集)
          </span>
        </div>
      )}
      {/* 右上ツール (z-45) と Pass switcher (z-45 right-center) を避けるため、
         警告 chip は **左下** 領域に集約。Pass1 採点ボタン (A/B) は中央〜下なので
         左下なら被らない。 */}
      {showShuttle && !shuttleQuery.isLoading && shuttleFrames.length === 0
       && !isTracknetRunning && !tracknetError && !tracknetCompleted && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); startTracknet() }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-warning"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 4.5rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="TrackNet をリモート実行"
        >
          <span className="inline-flex items-center gap-1">
            <MIcon name="play_arrow" size={11} />
            シャトル解析を実行
          </span>
        </button>
      )}
      {showShuttle && tracknetCompleted && shuttleFrames.length === 0 && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setTracknetJob(null); setTracknetJobId(null) }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 4.5rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="タップで閉じる"
        >
          <span className="inline-flex items-center gap-1">
            <MIcon name="check" size={11} />
            TrackNet 完了 (0 frames — Pass1 でラリーを記録してから再実行)
          </span>
        </button>
      )}
      {showShuttle && isTracknetRunning && (
        <div
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-accent"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 4.5rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          onClick={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
        >
          TrackNet 実行中… {Math.round((tracknetJob?.progress ?? 0) * 100)}%
        </div>
      )}
      {showShuttle && tracknetError && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setTracknetJob(null); setTracknetJobId(null) }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-danger max-w-[70vw]"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 4.5rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="タップで閉じる"
        >
          TrackNet エラー: {tracknetError.slice(0, 80)}
        </button>
      )}
      {showPlayers && !yoloQuery.isLoading && yoloFrames.length === 0
       && !isYoloRunning && !yoloError && !yoloCompleted && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); startYolo() }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-warning"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 7rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="YOLO をリモート実行"
        >
          <span className="inline-flex items-center gap-1">
            <MIcon name="play_arrow" size={11} />
            プレイヤー検出を実行
          </span>
        </button>
      )}
      {showPlayers && yoloCompleted && yoloFrames.length === 0 && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setYoloJob(null); setYoloJobId(null) }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 7rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="タップで閉じる"
        >
          <span className="inline-flex items-center gap-1">
            <MIcon name="check" size={11} />
            YOLO 完了 (0 frames — ROI / 動画範囲を確認)
          </span>
        </button>
      )}
      {showPlayers && isYoloRunning && (
        <div
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-accent"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 7rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          onClick={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
        >
          YOLO 実行中… {Math.round((yoloJob?.progress ?? 0) * 100)}%
        </div>
      )}
      {showPlayers && yoloError && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setYoloJob(null); setYoloJobId(null) }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-danger max-w-[70vw]"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 7rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="タップで閉じる"
        >
          YOLO エラー: {yoloError.slice(0, 80)}
        </button>
      )}
      {jobErr && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setJobErr('') }}
          className="absolute z-30 px-2 py-1 rounded text-[10px] ss-overlay-chip-danger max-w-[70vw]"
          style={{ bottom: 'calc(env(safe-area-inset-bottom) + 9.5rem)', left: 'calc(env(safe-area-inset-left) + 0.5rem)' }}
          title="タップで閉じる"
        >
          {jobErr}
        </button>
      )}
    </>
  )
}
