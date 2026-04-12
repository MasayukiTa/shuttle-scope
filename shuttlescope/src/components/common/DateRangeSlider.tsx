/**
 * DateRangeSlider — デュアルハンドル日付スライダー
 *
 * - A / B ハンドル両方とも自由に動かせる
 * - クロス可能: 常に 2点の間が選択範囲
 * - densityDates を渡すと試合データ密度をバーで可視化
 */
import { useRef, useCallback, useId, useMemo } from 'react'

interface DateRangeSliderProps {
  from: string | null        // YYYY-MM-DD
  to: string | null          // YYYY-MM-DD
  minDate?: string           // スライダー左端（省略: 4年前の1/1）
  maxDate?: string           // スライダー右端（省略: 今日）
  /** 密度表示用の日付一覧（試合日など） */
  densityDates?: string[]
  onChange: (from: string | null, to: string | null) => void
  isLight: boolean
}

// ─── 日付 ↔ 日数 変換 ────────────────────────────────────────────────────────

function toDay(dateStr: string, baseTs: number): number {
  return Math.round((new Date(dateStr).getTime() - baseTs) / 86400000)
}

function fromDay(day: number, baseTs: number): string {
  return new Date(baseTs + day * 86400000).toISOString().split('T')[0]
}

function defaultMin(): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 4)
  d.setMonth(0, 1)
  return d.toISOString().split('T')[0]
}

function defaultMax(): string {
  return new Date().toISOString().split('T')[0]
}

// ─── 密度バーデータ生成 ───────────────────────────────────────────────────────

interface DensityBar {
  pct: number      // トラック上の位置 (0–100%)
  height: number   // 正規化済みの高さ (0–1)
  count: number
}

function buildDensity(dates: string[], baseTs: number, totalDays: number): DensityBar[] {
  if (!dates.length || totalDays <= 0) return []

  // バケットサイズ: 範囲が短いほど細かく
  const bucketDays = totalDays <= 90 ? 7 : totalDays <= 365 ? 14 : totalDays <= 730 ? 30 : 60
  const numBuckets = Math.ceil(totalDays / bucketDays)
  const counts = new Array(numBuckets).fill(0)

  for (const d of dates) {
    const day = toDay(d, baseTs)
    if (day >= 0 && day <= totalDays) {
      counts[Math.min(Math.floor(day / bucketDays), numBuckets - 1)]++
    }
  }

  const CAP = 10  // 10件以上はすべて同じ高さ（突出バーで他が見えなくなるのを防ぐ）
  const cappedCounts = counts.map((c) => Math.min(c, CAP))
  const maxCount = Math.max(...cappedCounts, 1)
  return counts.map((count, i) => ({
    pct: ((i + 0.5) * bucketDays / totalDays) * 100,
    height: Math.min(count, CAP) / maxCount,
    count,
  }))
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────

const TRACK_W = 180  // px

export function DateRangeSlider({
  from,
  to,
  minDate,
  maxDate,
  densityDates = [],
  onChange,
  isLight,
}: DateRangeSliderProps) {
  const uid = useId()
  const trackRef = useRef<HTMLDivElement>(null)

  const minStr   = minDate ?? defaultMin()
  const maxStr   = maxDate ?? defaultMax()
  const baseTs   = new Date(minStr).getTime()
  const totalDays = Math.max(1, toDay(maxStr, baseTs))

  // posA = ハンドルA の日数位置, posB = ハンドルB の日数位置
  const posA = from ? Math.max(0, Math.min(toDay(from, baseTs), totalDays)) : 0
  const posB = to   ? Math.max(0, Math.min(toDay(to,   baseTs), totalDays)) : totalDays

  // 選択範囲は常に min〜max（クロス時も正しく）
  const selMin = Math.min(posA, posB)
  const selMax = Math.max(posA, posB)
  const selMinPct = (selMin / totalDays) * 100
  const selMaxPct = (selMax / totalDays) * 100

  // 密度バー
  const densityBars = useMemo(
    () => buildDensity(densityDates, baseTs, totalDays),
    [densityDates, baseTs, totalDays]
  )

  // 年区切り目盛り
  const yearTicks = useMemo(() => {
    const ticks: { label: string; pct: number }[] = []
    const sy = new Date(minStr).getFullYear()
    const ey = new Date(maxStr).getFullYear()
    for (let y = sy + 1; y <= ey; y++) {
      const day = toDay(`${y}-01-01`, baseTs)
      if (day > 0 && day < totalDays) {
        ticks.push({ label: `'${String(y).slice(2)}`, pct: (day / totalDays) * 100 })
      }
    }
    return ticks
  }, [minStr, maxStr, baseTs, totalDays])

  // ドラッグ処理（pointer capture で確実に追跡）
  const makeDragHandler = useCallback(
    (handle: 'a' | 'b') => {
      function onPointerMove(e: PointerEvent) {
        const track = trackRef.current
        if (!track) return
        const rect = track.getBoundingClientRect()
        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
        const day = Math.round(ratio * totalDays)

        if (handle === 'a') {
          // ハンドルA は from 位置として渡す（クロス許容: 親で min/max を計算）
          onChange(
            day === 0 ? null : fromDay(day, baseTs),
            posB === totalDays ? null : fromDay(posB, baseTs),
          )
        } else {
          onChange(
            posA === 0 ? null : fromDay(posA, baseTs),
            day === totalDays ? null : fromDay(day, baseTs),
          )
        }
      }
      return (e: React.PointerEvent<HTMLDivElement>) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        const el = e.currentTarget
        const listener = onPointerMove as EventListener
        el.addEventListener('pointermove', listener)
        el.addEventListener('pointerup', () => el.removeEventListener('pointermove', listener), { once: true })
      }
    },
    [posA, posB, totalDays, baseTs, onChange]
  )

  // ─── スタイル定数 ───────────────────────────────────────────────────────────
  const trackBg  = isLight ? '#e2e8f0' : '#374151'
  const fillBg   = isLight ? '#3b82f6' : '#2563eb'
  const thumbBg  = isLight ? '#3b82f6' : '#60a5fa'
  const thumbBdr = isLight ? '#ffffff' : '#111827'
  const barFill  = isLight ? 'rgba(59,130,246,0.35)' : 'rgba(96,165,250,0.30)'
  const barFillSel = isLight ? 'rgba(59,130,246,0.75)' : 'rgba(96,165,250,0.65)'
  const tickCol  = isLight ? '#94a3b8' : '#6b7280'
  const labelCol = isLight ? '#64748b' : '#9ca3af'

  const DENSITY_H = 24  // 密度バーエリアの高さ px
  const TRACK_H   = 16  // トラックエリアの高さ px
  const TICK_H    = 12  // 年ラベルエリアの高さ px
  const THUMB_R   = 7   // ハンドル半径 px

  const pctA = (posA / totalDays) * 100
  const pctB = (posB / totalDays) * 100

  return (
    <div className="flex items-center gap-2 shrink-0 select-none">
      {/* スライダー本体 */}
      <div style={{ width: TRACK_W, userSelect: 'none' }}>

        {/* 密度バーエリア */}
        <div
          style={{ height: DENSITY_H, position: 'relative' }}
          title={densityBars.length ? '縦棒 = 試合数の密度' : ''}
        >
          {densityBars.map((bar, i) => {
            const inSel = bar.pct >= selMinPct && bar.pct <= selMaxPct
            return (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  bottom: 0,
                  left: `${bar.pct}%`,
                  transform: 'translateX(-50%)',
                  width: Math.max(2, TRACK_W / densityBars.length - 1),
                  height: `${Math.max(2, bar.height * DENSITY_H)}px`,
                  backgroundColor: inSel ? barFillSel : barFill,
                  borderRadius: 1,
                }}
                title={`${bar.count}試合`}
              />
            )
          })}
        </div>

        {/* トラック + ハンドル */}
        <div
          ref={trackRef}
          style={{
            position: 'relative',
            height: TRACK_H,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          {/* ベーストラック */}
          <div
            style={{
              position: 'absolute',
              inset: `0 ${THUMB_R}px`,
              height: 4,
              top: '50%',
              transform: 'translateY(-50%)',
              backgroundColor: trackBg,
              borderRadius: 2,
            }}
          />

          {/* 選択範囲フィル */}
          <div
            style={{
              position: 'absolute',
              left: `calc(${selMinPct}% * (${TRACK_W - THUMB_R * 2} / ${TRACK_W}) + ${THUMB_R}px)`,
              width: `calc(${selMaxPct - selMinPct}% * (${TRACK_W - THUMB_R * 2} / ${TRACK_W}))`,
              height: 4,
              top: '50%',
              transform: 'translateY(-50%)',
              backgroundColor: fillBg,
              borderRadius: 2,
            }}
          />

          {/* ハンドルA（from） */}
          <div
            onPointerDown={makeDragHandler('a')}
            style={{
              position: 'absolute',
              left: `calc(${pctA}% * (${TRACK_W - THUMB_R * 2} / ${TRACK_W}) + ${THUMB_R}px)`,
              top: '50%',
              transform: 'translate(-50%, -50%)',
              width: THUMB_R * 2,
              height: THUMB_R * 2,
              borderRadius: '50%',
              backgroundColor: thumbBg,
              border: `2px solid ${thumbBdr}`,
              boxShadow: '0 1px 4px rgba(0,0,0,0.35)',
              cursor: 'grab',
              zIndex: pctA > 50 ? 3 : 2,
              touchAction: 'none',
            }}
            title={fromDay(posA, baseTs)}
          />

          {/* ハンドルB（to） */}
          <div
            onPointerDown={makeDragHandler('b')}
            style={{
              position: 'absolute',
              left: `calc(${pctB}% * (${TRACK_W - THUMB_R * 2} / ${TRACK_W}) + ${THUMB_R}px)`,
              top: '50%',
              transform: 'translate(-50%, -50%)',
              width: THUMB_R * 2,
              height: THUMB_R * 2,
              borderRadius: '50%',
              backgroundColor: thumbBg,
              border: `2px solid ${thumbBdr}`,
              boxShadow: '0 1px 4px rgba(0,0,0,0.35)',
              cursor: 'grab',
              zIndex: pctA > 50 ? 2 : 3,
              touchAction: 'none',
            }}
            title={fromDay(posB, baseTs)}
          />
        </div>

        {/* 年区切り目盛り */}
        {yearTicks.length > 0 && (
          <div style={{ position: 'relative', height: TICK_H, fontSize: 9, color: tickCol }}>
            {yearTicks.map(({ label, pct }) => (
              <span
                key={label}
                style={{
                  position: 'absolute',
                  left: `${pct}%`,
                  transform: 'translateX(-50%)',
                  pointerEvents: 'none',
                }}
              >
                {label}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 選択期間テキスト */}
      <span
        style={{ fontSize: 10, color: labelCol, minWidth: 88, lineHeight: 1.3, whiteSpace: 'nowrap' }}
      >
        {fromDay(selMin, baseTs).slice(0, 7)}
        <br />
        {'– ' + fromDay(selMax, baseTs).slice(0, 7)}
      </span>
    </div>
  )
}
