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
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ShuttleTrackOverlay, type ShuttleFrame } from '@/components/annotation/ShuttleTrackOverlay'
import { PlayerPositionOverlay } from '@/components/annotation/PlayerPositionOverlay'

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


export function MobileCVOverlay({
  matchId,
  currentSec,
  videoWidth,
  videoHeight,
  showCourt,
  showShuttle,
  showPlayers,
}: Props) {
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
    </>
  )
}
