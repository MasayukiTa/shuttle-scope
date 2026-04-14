/**
 * PlayerTrackingOverlay — 選手識別トラックをビデオ上に表示する。
 *
 * 2つのモード:
 *   tagging=false (通常): 識別済みトラックを bbox で表示。一時停止中はホバーで名前表示。
 *   tagging=true  (タグ付け): 1フレーム検出結果を表示し、クリックで選手を割り当てる。
 */
import { useState, useCallback } from 'react'
import { clsx } from 'clsx'

// ── 型定義 ────────────────────────────────────────────────────────────────────

export interface TrackedPlayer {
  player_key: string  // 'player_a' | 'partner_a' | 'player_b' | 'partner_b' | 'other'
  bbox: [number, number, number, number]  // x1n, y1n, x2n, y2n (0–1 正規化)
  cx_n?: number
  cy_n?: number
  lost?: boolean
}

export interface TrackFrame {
  frame_idx: number
  timestamp_sec: number
  players: TrackedPlayer[]
}

export interface RawDetection {
  bbox: [number, number, number, number]
  label?: string
  confidence?: number
}

export interface PlayerOption {
  key: string   // 'player_a' | 'partner_a' | 'player_b' | 'partner_b' | 'other'
  name: string
}

interface Props {
  /** 通常モード: 全フレームの識別済みトラック */
  trackFrames: TrackFrame[]
  /** タグ付けモード: 1フレーム検出結果 */
  frameDetections: RawDetection[]
  /** 現在の再生位置（秒） */
  currentSec: number
  /** 一時停止中か（ホバーUI表示制御） */
  isPaused: boolean
  /** 表示/非表示 */
  visible: boolean
  /** タグ付けモードか */
  tagging: boolean
  /** 割り当て候補の選手一覧 */
  playerOptions: PlayerOption[]
  /** タグ付けモードでの割り当て変更 */
  onAssign: (detectionIndex: number, playerKey: string) => void
  /** 現在の割り当て状態（taggingモード用） */
  assignments: Record<number, string>  // detection_index → player_key
  isLight: boolean
}

// ── 定数 ─────────────────────────────────────────────────────────────────────

const KEY_COLORS: Record<string, string> = {
  player_a:  '#3b82f6',  // blue
  partner_a: '#60a5fa',  // blue-light
  player_b:  '#f59e0b',  // amber
  partner_b: '#fbbf24',  // amber-light
  other:     '#6b7280',  // gray
}

const LOST_OPACITY = 0.35

/** 現在時刻に最も近いフレームを返す（±2s 以内） */
function findNearest(frames: TrackFrame[], sec: number): TrackFrame | null {
  if (!frames.length) return null
  let best: TrackFrame | null = null
  let bestGap = Infinity
  for (const f of frames) {
    const gap = Math.abs(f.timestamp_sec - sec)
    if (gap < bestGap) { bestGap = gap; best = f }
  }
  return bestGap <= 2.0 ? best : null
}

// ── コンポーネント ─────────────────────────────────────────────────────────────

export function PlayerTrackingOverlay({
  trackFrames,
  frameDetections,
  currentSec,
  isPaused,
  visible,
  tagging,
  playerOptions,
  onAssign,
  assignments,
  isLight,
}: Props) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)
  const [openDropdown, setOpenDropdown] = useState<number | null>(null)

  const nearestFrame = tagging ? null : findNearest(trackFrames, currentSec)

  const stopProp = useCallback((e: React.MouseEvent) => e.stopPropagation(), [])

  if (!visible) return null

  // ─── タグ付けモード ──────────────────────────────────────────────────────────
  if (tagging) {
    const hasDetections = frameDetections.length > 0
    return (
      <div className="absolute inset-0" style={{ zIndex: 25, pointerEvents: hasDetections ? 'auto' : 'none' }}>
        {frameDetections.map((det, i) => {
          const [x1n, y1n, x2n, y2n] = det.bbox
          const assignedKey = assignments[i] ?? null
          const color = assignedKey ? (KEY_COLORS[assignedKey] ?? '#6b7280') : '#ffffff'
          const assigned = playerOptions.find(p => p.key === assignedKey)

          return (
            <div
              key={i}
              className="absolute"
              style={{
                left:   `${x1n * 100}%`,
                top:    `${y1n * 100}%`,
                width:  `${(x2n - x1n) * 100}%`,
                height: `${(y2n - y1n) * 100}%`,
                border: `2px solid ${color}`,
                backgroundColor: `${color}18`,
                cursor: 'pointer',
              }}
              onClick={(e) => {
                e.stopPropagation()
                setOpenDropdown(openDropdown === i ? null : i)
              }}
            >
              {/* ラベル */}
              <div
                className="absolute left-0 top-0 text-[10px] font-semibold px-1 leading-4 select-none truncate max-w-full"
                style={{ backgroundColor: color, color: '#fff', transform: 'translateY(-100%)' }}
              >
                {assigned?.name ?? `検出 ${i + 1}`}
              </div>

              {/* ドロップダウン */}
              {openDropdown === i && (
                <div
                  className={clsx(
                    'absolute z-50 rounded shadow-lg border min-w-[120px] text-xs py-0.5',
                    isLight ? 'bg-white border-gray-200 text-gray-800' : 'bg-gray-900 border-gray-700 text-gray-100'
                  )}
                  style={{ top: '100%', left: 0 }}
                  onClick={stopProp}
                >
                  {playerOptions.map(opt => (
                    <button
                      key={opt.key}
                      className={clsx(
                        'w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-opacity-10',
                        assignments[i] === opt.key
                          ? isLight ? 'bg-blue-50 font-semibold' : 'bg-blue-900/30 font-semibold'
                          : isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-800'
                      )}
                      onClick={() => {
                        onAssign(i, opt.key)
                        setOpenDropdown(null)
                      }}
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: KEY_COLORS[opt.key] ?? '#6b7280' }}
                      />
                      {opt.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {/* ヒント */}
        {frameDetections.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <span className="bg-black/80 text-xs px-3 py-1.5 rounded-full" style={{ color: '#fff' }}>
              人物が検出されませんでした（3秒後に閉じます）
            </span>
          </div>
        )}
      </div>
    )
  }

  // ─── 通常モード ──────────────────────────────────────────────────────────────
  if (!nearestFrame) return null

  return (
    <div
      className="absolute inset-0"
      style={{ zIndex: 22, pointerEvents: isPaused ? 'auto' : 'none' }}
    >
      {nearestFrame.players.map((p, i) => {
        const [x1n, y1n, x2n, y2n] = p.bbox
        const color = KEY_COLORS[p.player_key] ?? '#6b7280'
        const opacity = p.lost ? LOST_OPACITY : 0.9
        const isHovered = hoveredIdx === i
        const displayName = playerOptions.find(o => o.key === p.player_key)?.name ?? p.player_key

        return (
          <div
            key={i}
            className="absolute transition-opacity"
            style={{
              left:   `${x1n * 100}%`,
              top:    `${y1n * 100}%`,
              width:  `${(x2n - x1n) * 100}%`,
              height: `${(y2n - y1n) * 100}%`,
              border: `2px solid ${color}`,
              backgroundColor: `${color}${p.lost ? '10' : '15'}`,
              opacity,
              cursor: isPaused ? 'default' : 'none',
            }}
            onMouseEnter={() => isPaused && setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
          >
            {/* ホバー時の名前ツールチップ */}
            {isHovered && isPaused && (
              <div
                className={clsx(
                  'absolute left-1/2 -translate-x-1/2 whitespace-nowrap text-[11px] font-semibold',
                  'px-2 py-0.5 rounded shadow-lg pointer-events-none select-none',
                  isLight ? 'bg-white text-gray-900 border border-gray-200' : 'bg-gray-900 text-white border border-gray-700'
                )}
                style={{
                  top: '-26px',
                  zIndex: 50,
                }}
              >
                <span className="w-2 h-2 rounded-full inline-block mr-1 align-middle" style={{ backgroundColor: color }} />
                {displayName}
                {p.lost && <span className="ml-1 opacity-60 text-[9px]">(ロスト)</span>}
              </div>
            )}

            {/* 常時表示: 小さな名前ラベル（bbox左上） */}
            {!p.lost && (
              <div
                className="absolute left-0 top-0 text-[9px] font-semibold px-1 leading-4 select-none"
                style={{
                  backgroundColor: color,
                  color: '#fff',
                  transform: 'translateY(-100%)',
                  opacity: 0.85,
                }}
              >
                {displayName}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
