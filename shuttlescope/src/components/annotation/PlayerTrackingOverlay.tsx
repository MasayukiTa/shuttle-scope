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
  hist?: number[]   // 胴体 Hue ヒスト（外観ギャラリー用、backend が付与）
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
  /** フレーム検出APIエラー（nullなら正常） */
  frameDetectError?: string | null
  /** フレーム検出デバッグ情報 */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  frameDetectDebug?: Record<string, any> | null
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
  frameDetectError,
  frameDetectDebug,
}: Props) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  const nearestFrame = tagging ? null : findNearest(trackFrames, currentSec)

  if (!visible) return null

  // ─── タグ付けモード ──────────────────────────────────────────────────────────
  if (tagging) {
    const hasDetections = frameDetections.length > 0

    // bbox クリックで役割をサイクル切り替え（未割当 → A → B → ... → 未割当）
    // 他の bbox に既に割り当て済みのキーはスキップする（重複禁止）
    const cycleAssign = (i: number) => {
      const keys = playerOptions.map(p => p.key)
      // 他の bbox が使用中のキー（'other' は重複 OK）
      const usedByOthers = new Set(
        Object.entries(assignments)
          .filter(([idx, k]) => Number(idx) !== i && k && k !== 'other')
          .map(([, k]) => k)
      )
      const availableKeys = keys.filter(k => k === 'other' || !usedByOthers.has(k))
      const cur = assignments[i] ?? null
      const curIdx = cur ? availableKeys.indexOf(cur) : -1
      // 現在値の次の利用可能キーへ進む
      const nextKey = availableKeys[curIdx + 1] ?? null
      if (nextKey) onAssign(i, nextKey)
      else onAssign(i, '')  // 未割当に戻す
    }

    return (
      <div className="absolute inset-0" style={{ zIndex: 25, pointerEvents: hasDetections ? 'auto' : 'none' }}>
        {frameDetections.map((det, i) => {
          const [x1n, y1n, x2n, y2n] = det.bbox
          const assignedKey = assignments[i] ?? null
          const color = assignedKey ? (KEY_COLORS[assignedKey] ?? '#6b7280') : '#e5e7eb'
          const assigned = playerOptions.find(p => p.key === assignedKey)
          const isHovered = hoveredIdx === i

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
                backgroundColor: isHovered ? `${color}30` : `${color}15`,
                cursor: 'pointer',
                transition: 'background-color 0.1s',
              }}
              onClick={(e) => { e.stopPropagation(); cycleAssign(i) }}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
              title="クリックで役割切り替え"
            >
              {/* 番号バッジ + 割当名 */}
              <div
                className="absolute left-0 top-0 flex items-center gap-0.5 text-[10px] font-bold px-1 leading-4 select-none"
                style={{ backgroundColor: color, color: '#fff', transform: 'translateY(-100%)', whiteSpace: 'nowrap' }}
              >
                <span>{i + 1}</span>
                {assigned && <span className="font-normal opacity-90">: {assigned.name}</span>}
              </div>
            </div>
          )
        })}

        {/* ヒント / エラー表示 */}
        {frameDetections.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="flex flex-col items-center gap-1 max-w-sm text-center">
              {frameDetectError ? (
                <>
                  <span className="bg-red-900/90 text-xs px-3 py-1.5 rounded-full" style={{ color: '#fca5a5' }}>
                    検出エラー（3秒後に閉じます）
                  </span>
                  <span className="bg-black/80 text-[10px] px-2 py-1 rounded" style={{ color: '#fca5a5' }}>
                    {frameDetectError}
                  </span>
                </>
              ) : (
                <span className="bg-black/80 text-xs px-3 py-1.5 rounded-full" style={{ color: '#fff' }}>
                  人物が検出されませんでした（3秒後に自動で閉じます）
                </span>
              )}
              {/* 診断情報（検出ゼロ時のみ表示） */}
              {frameDetectDebug && (
                <div className="bg-black/85 text-[9px] px-2 py-1.5 rounded font-mono text-left" style={{ color: '#94a3b8' }}>
                  <div>backend: {frameDetectDebug.backend ?? '—'}</div>
                  {frameDetectDebug.frame_mean_brightness !== undefined && (
                    <div>frame brightness: {frameDetectDebug.frame_mean_brightness}</div>
                  )}
                  {frameDetectDebug.person_score_max !== undefined && (
                    <div>
                      max person score: <span style={{ color: frameDetectDebug.person_score_max >= 0.10 ? '#fbbf24' : '#ef4444' }}>
                        {frameDetectDebug.person_score_max}
                      </span>
                      {' '}(閾値: {frameDetectDebug.threshold})
                    </div>
                  )}
                  {frameDetectDebug.person_score_top5 && (
                    <div>top5: [{(frameDetectDebug.person_score_top5 as number[]).join(', ')}]</div>
                  )}
                  {frameDetectDebug.warning && (
                    <div style={{ color: '#f87171' }}>⚠ {frameDetectDebug.warning}</div>
                  )}
                  {frameDetectDebug.error && (
                    <div style={{ color: '#f87171' }}>error: {frameDetectDebug.error}</div>
                  )}
                </div>
              )}
            </div>
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
