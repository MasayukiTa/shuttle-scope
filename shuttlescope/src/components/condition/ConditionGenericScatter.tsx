import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'
import { pearson } from '@/utils/stats'
import { RoleGuard } from '@/components/common/RoleGuard'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { catColor, catColorByIndex } from '@/styles/categoricalPalette'
import { coolwarm } from '@/styles/colors'

// 汎用 X/Y/色 散布図 (coach/analyst 限定)
// ConditionRecord[] から任意の 2 指標 + 色分けを動的に選んで表示
interface Props {
  playerId: number
  isLight: boolean
}

// 指標キー候補 (ConditionRecord 上のフィールド)
type MetricKey =
  | 'hooper_sleep'
  | 'hooper_soreness'
  | 'hooper_stress'
  | 'hooper_fatigue'
  | 'hooper_index'
  | 'session_rpe'
  | 'session_load'
  | 'sleep_hours'
  | 'weight_kg'
  | 'muscle_mass_kg'
  | 'body_fat_pct'

const METRIC_KEYS: MetricKey[] = [
  'hooper_sleep',
  'hooper_soreness',
  'hooper_stress',
  'hooper_fatigue',
  'hooper_index',
  'session_rpe',
  'session_load',
  'sleep_hours',
  'weight_kg',
  'muscle_mass_kg',
  'body_fat_pct',
]

type ColorMode = 'month' | 'weekday' | 'value'

function toFiniteNumber(v: unknown): number | null {
  if (v == null) return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

function getMetric(rec: ConditionRecord, key: MetricKey): number | null {
  return toFiniteNumber((rec as unknown as Record<string, unknown>)[key])
}

// Categorical 識別: 12 色ベタは色弱で破綻するため、
//   - month (1-12): 月の四半期 (1-3/4-6/7-9/10-12) を 4 色に集約。「春夏秋冬」
//     表記は東南アジア / 南半球で誤解になるため使わない (四半期グループのみ)。
//   - weekday (0-6): 7 色 — catColorByIndex で展開
// (Design Language §6 準拠)
function monthQuarterKey(month: number): 'Cool' | 'Green' | 'Warm' | 'Amber' {
  if (month <= 3) return 'Cool'
  if (month <= 6) return 'Green'
  if (month <= 9) return 'Warm'
  return 'Amber'
}
function monthColorMode(month: number, isLight: boolean): string {
  return catColor(monthQuarterKey(month), isLight)
}
function weekdayColorMode(weekday: number, isLight: boolean): string {
  // 0=日 / 6=土 を CAT_ORDER の最初の 7 色に割り当てる
  return catColorByIndex(weekday, isLight)
}

// 連続値 → coolwarm スケール (Design Language §2.4)
// HSL spin ではなく coolwarm を逆方向に使うことで青→白→赤の divergent
function valueColorMode(v: number, min: number, max: number): string {
  if (!Number.isFinite(v) || min === max) return '#94a3b8' // N_GRAY[400]
  const t = Math.max(0, Math.min(1, (v - min) / (max - min)))
  return coolwarm(t)
}

interface Point {
  x: number
  y: number
  date: string
  color: string
  zLabel?: string
}

export function ConditionGenericScatter({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data: records, isLoading } = useConditions(playerId, { limit: 200 })

  // 実データで値が 1 件以上存在する指標のみセレクト候補にする
  const availableMetrics = useMemo<MetricKey[]>(() => {
    const recs = records ?? []
    return METRIC_KEYS.filter((k) =>
      recs.some((r) => getMetric(r, k) != null),
    )
  }, [records])

  const defaultX: MetricKey = availableMetrics.includes('hooper_index')
    ? 'hooper_index'
    : availableMetrics[0] ?? 'hooper_index'
  const defaultY: MetricKey = availableMetrics.includes('session_rpe')
    ? 'session_rpe'
    : availableMetrics[1] ?? availableMetrics[0] ?? 'session_rpe'

  const [x, setX] = useState<MetricKey>(defaultX)
  const [y, setY] = useState<MetricKey>(defaultY)
  const [colorMode, setColorMode] = useState<ColorMode>('month')
  const [zKey, setZKey] = useState<MetricKey>(defaultX)

  const panelBg = 'bg-[var(--ss-surface-1)]'
  const borderColor = 'border-[var(--ss-border)]'
  const textMuted = 'text-[var(--ss-t3)]'
  const selectCls = 'border border-[var(--ss-border-strong)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] rounded-ss-md px-2 py-1 text-sm'

  // データ整形 (有限値ペアのみ)
  const { points, r, n } = useMemo(() => {
    const recs = records ?? []
    const filtered: Array<{
      x: number
      y: number
      date: string
      month: number
      weekday: number
      z: number | null
    }> = []
    for (const rec of recs) {
      const xv = getMetric(rec, x)
      const yv = getMetric(rec, y)
      if (xv == null || yv == null) continue
      const d = rec.measured_at ? new Date(rec.measured_at) : null
      const month = d && !isNaN(d.getTime()) ? d.getMonth() + 1 : 1
      // 0=月曜
      const weekday =
        d && !isNaN(d.getTime()) ? (d.getDay() + 6) % 7 : 0
      const z = getMetric(rec, zKey)
      filtered.push({
        x: xv,
        y: yv,
        date: rec.measured_at ?? '',
        month,
        weekday,
        z,
      })
    }

    // 色決定
    let zMin = Infinity
    let zMax = -Infinity
    if (colorMode === 'value') {
      for (const f of filtered) {
        if (f.z != null) {
          if (f.z < zMin) zMin = f.z
          if (f.z > zMax) zMax = f.z
        }
      }
    }

    const pts: Point[] = filtered.map((f) => {
      let color = catColor('Cool', isLight)
      if (colorMode === 'month') {
        color = monthColorMode(f.month, isLight)
      } else if (colorMode === 'weekday') {
        color = weekdayColorMode(f.weekday, isLight)
      } else if (colorMode === 'value') {
        color =
          f.z != null && Number.isFinite(zMin) && Number.isFinite(zMax)
            ? valueColorMode(f.z, zMin, zMax)
            : (isLight ? '#94a3b8' : '#64748b')
      }
      return {
        x: f.x,
        y: f.y,
        date: f.date,
        color,
        zLabel: f.z != null ? String(f.z) : undefined,
      }
    })

    const rr = pearson(
      pts.map((p) => p.x),
      pts.map((p) => p.y),
    )
    return { points: pts, r: rr, n: pts.length }
  }, [records, x, y, zKey, colorMode, isLight])

  return (
    <RoleGuard allowedRoles={['coach', 'analyst']} fallback={null}>
      <section className={`rounded-ss-lg border ${borderColor} ${panelBg} p-4`}>
        <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
          <h2 className="text-sm font-semibold text-[var(--ss-t1)]">
            {t('condition.generic_scatter.title')}
          </h2>
          {n > 0 && <ConfidenceBadge sampleSize={n} />}
        </div>
        <p className={`text-xs ${textMuted} mb-3`}>
          {t('condition.generic_scatter.intro')}
        </p>

        <div className="flex flex-wrap items-center gap-3 mb-3">
          <div className="flex items-center gap-2">
            <label className={`text-xs ${textMuted}`}>
              {t('condition.generic_scatter.x_axis')}
            </label>
            <select
              className={selectCls}
              value={x}
              onChange={(e) => setX(e.target.value as MetricKey)}
            >
              {availableMetrics.map((k) => (
                <option key={k} value={k}>
                  {t(`condition.generic_scatter.metric.${k}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className={`text-xs ${textMuted}`}>
              {t('condition.generic_scatter.y_axis')}
            </label>
            <select
              className={selectCls}
              value={y}
              onChange={(e) => setY(e.target.value as MetricKey)}
            >
              {availableMetrics.map((k) => (
                <option key={k} value={k}>
                  {t(`condition.generic_scatter.metric.${k}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className={`text-xs ${textMuted}`}>
              {t('condition.generic_scatter.color_axis')}
            </label>
            <select
              className={selectCls}
              value={colorMode}
              onChange={(e) => setColorMode(e.target.value as ColorMode)}
            >
              <option value="month">
                {t('condition.generic_scatter.color_mode.month')}
              </option>
              <option value="weekday">
                {t('condition.generic_scatter.color_mode.weekday')}
              </option>
              <option value="value">
                {t('condition.generic_scatter.color_mode.value')}
              </option>
            </select>
          </div>
          {colorMode === 'value' && (
            <div className="flex items-center gap-2">
              <label className={`text-xs ${textMuted}`}>
                {t('condition.generic_scatter.z_axis')}
              </label>
              <select
                className={selectCls}
                value={zKey}
                onChange={(e) => setZKey(e.target.value as MetricKey)}
              >
                {availableMetrics.map((k) => (
                  <option key={k} value={k}>
                    {t(`condition.generic_scatter.metric.${k}`)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {isLoading ? (
          <div className={`${textMuted} text-xs`}>...</div>
        ) : n < 2 ? (
          <div className={`${textMuted} text-xs`}>
            {t('condition.generic_scatter.no_data')}
          </div>
        ) : (
          <>
            <div style={{ width: '100%', height: 300 }}>
              <ResponsiveContainer>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={'var(--ss-border)'}
                  />
                  <XAxis
                    type="number"
                    dataKey="x"
                    name={t(`condition.generic_scatter.metric.${x}`)}
                    tick={{ fill: 'var(--ss-t3)', fontSize: 11 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name={t(`condition.generic_scatter.metric.${y}`)}
                    tick={{ fill: 'var(--ss-t3)', fontSize: 11 }}
                  />
                  <ZAxis range={[60, 60]} />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    contentStyle={{
                      backgroundColor: 'var(--ss-surface-1)',
                      border: `1px solid var(--ss-border)`,
                      fontSize: 12,
                      borderRadius: 6,
                    }}
                    formatter={(value: number | string, name: string) => {
                      if (name === 'x')
                        return [value, t(`condition.generic_scatter.metric.${x}`)]
                      if (name === 'y')
                        return [value, t(`condition.generic_scatter.metric.${y}`)]
                      return [value, name]
                    }}
                    labelFormatter={(_, payload) => {
                      const p = payload && payload[0] ? (payload[0].payload as Point) : null
                      return p
                        ? `${t('condition.generic_scatter.tooltip_date')}: ${p.date}`
                        : ''
                    }}
                  />
                  <Scatter data={points}>
                    {points.map((p, i) => (
                      <Cell key={i} fill={p.color} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className={`mt-2 flex flex-wrap items-center gap-2 text-[11px] ${textMuted}`}>
              {colorMode === 'month' && (
                <>
                  <span>{t('condition.generic_scatter.legend_month')}:</span>
                  {/* 月の四半期グループ (12 色ベタは色弱不可、季節呼称は地域依存なので使わない) */}
                  {[
                    { label: '1-3月', key: 'Cool' as const },
                    { label: '4-6月', key: 'Green' as const },
                    { label: '7-9月', key: 'Warm' as const },
                    { label: '10-12月', key: 'Amber' as const },
                  ].map(({ label, key }) => (
                    <span key={key} className="inline-flex items-center gap-1">
                      <span style={{ width: 10, height: 10, background: catColor(key, isLight), display: 'inline-block', borderRadius: 9999 }} />
                      {label}
                    </span>
                  ))}
                </>
              )}
              {colorMode === 'weekday' && (
                <>
                  <span>{t('condition.generic_scatter.legend_weekday')}:</span>
                  {['月', '火', '水', '木', '金', '土', '日'].map((w, i) => (
                    <span key={w} className="inline-flex items-center gap-1">
                      <span style={{ width: 10, height: 10, background: catColorByIndex(i, isLight), display: 'inline-block', borderRadius: 9999 }} />
                      {w}
                    </span>
                  ))}
                </>
              )}
              {colorMode === 'value' && (
                <span className="inline-flex items-center gap-2">
                  <span>{t('condition.generic_scatter.legend_value')}:</span>
                  {/* coolwarm grad: 青 (低) → 白 (中) → 赤 (高) */}
                  <span style={{ width: 120, height: 10, background: 'linear-gradient(to right, #3b4cc0, #ffffff, #b40426)', border: `1px solid var(--ss-border)` }} />
                  <span>{t('auto.ConditionGenericScatter.k1')}</span>
                </span>
              )}
            </div>
            <div className={`mt-2 flex flex-wrap gap-4 text-xs ${textMuted}`}>
              <span>
                {t('condition.generic_scatter.pearson_r')}:{' '}
                <span className="font-mono ss-num">
                  {r != null ? r.toFixed(3) : '—'}
                </span>
              </span>
              <span>
                {t('condition.generic_scatter.sample_size')}:{' '}
                <span className="font-mono ss-num">{n}</span>
              </span>
            </div>
          </>
        )}
      </section>
    </RoleGuard>
  )
}
