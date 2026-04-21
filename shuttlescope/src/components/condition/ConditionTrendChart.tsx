import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'

// 体調タブ解析サブタブ用: 時系列トレンドチャート
// - CCS 折れ線 + 28日移動平均
// - F1〜F5 因子別折れ線 (coach/analyst のみ)
// - 補助指標 (weight/muscle/bodyfat) の推移
interface Props {
  playerId: number
  isLight: boolean
}

interface ChartPoint {
  date: string           // YYYY-MM-DD
  ts: number             // epoch ms (数値軸用)
  ccs: number | null
  ccs_ma28: number | null
  f1: number | null
  f2: number | null
  f3: number | null
  f4: number | null
  f5: number | null
  weight_kg: number | null
  muscle_mass_kg: number | null
  body_fat_pct: number | null
}

// 28日移動平均 (サンプル < 3 は null)
function compute28dMa(points: Array<{ ts: number; ccs: number | null }>): Array<number | null> {
  const DAY = 24 * 60 * 60 * 1000
  const window = 28 * DAY
  const out: Array<number | null> = []
  for (let i = 0; i < points.length; i++) {
    const cur = points[i]
    if (cur.ccs == null) {
      out.push(null)
      continue
    }
    const lo = cur.ts - window
    let sum = 0
    let n = 0
    for (let j = i; j >= 0; j--) {
      const p = points[j]
      if (p.ts < lo) break
      if (p.ccs != null) {
        sum += p.ccs
        n += 1
      }
    }
    out.push(n >= 3 ? sum / n : null)
  }
  return out
}

function toPoints(records: ConditionRecord[]): ChartPoint[] {
  // measured_at 昇順
  const sorted = [...records]
    .filter((r) => !!r.measured_at)
    .sort((a, b) => (a.measured_at! < b.measured_at! ? -1 : 1))

  const base = sorted.map((r) => {
    // 型定義では f1〜f5 は ConditionResult 側にあるが、API が ConditionRecord にも乗せうる
    const anyR = r as unknown as Record<string, number | null | undefined>
    const ts = new Date(r.measured_at as string).getTime()
    return {
      date: (r.measured_at as string).slice(0, 10),
      ts,
      ccs: (anyR.ccs as number | null | undefined) ?? null,
      f1: (anyR.f1 as number | null | undefined) ?? null,
      f2: (anyR.f2 as number | null | undefined) ?? null,
      f3: (anyR.f3 as number | null | undefined) ?? null,
      f4: (anyR.f4 as number | null | undefined) ?? null,
      f5: (anyR.f5 as number | null | undefined) ?? null,
      weight_kg: r.weight_kg ?? null,
      muscle_mass_kg: r.muscle_mass_kg ?? null,
      body_fat_pct: r.body_fat_pct ?? null,
    }
  })

  const ma = compute28dMa(base.map((p) => ({ ts: p.ts, ccs: p.ccs })))
  return base.map((p, i) => ({ ...p, ccs_ma28: ma[i] }))
}

export function ConditionTrendChart({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useConditions(playerId, { limit: 200 })

  const points = useMemo<ChartPoint[]>(() => toPoints(data ?? []), [data])

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const sectionTitle = isLight ? 'text-gray-800' : 'text-gray-100'
  const gridStroke = isLight ? '#e5e7eb' : '#374151'
  const axisTick = { fill: isLight ? '#374151' : '#9ca3af', fontSize: 11 }
  const tooltipStyle = {
    backgroundColor: isLight ? '#ffffff' : '#1f2937',
    border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
    fontSize: 12,
  }

  // 補助指標は「1点でも値がある列」だけ描画
  const hasWeight = points.some((p) => p.weight_kg != null)
  const hasMuscle = points.some((p) => p.muscle_mass_kg != null)
  const hasBodyFat = points.some((p) => p.body_fat_pct != null)
  const hasAnyAux = hasWeight || hasMuscle || hasBodyFat

  const hasCcs = points.some((p) => p.ccs != null)

  if (isLoading) {
    return (
      <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
        <h2 className="text-sm font-semibold">{t('condition.trend.title')}</h2>
        <div className={`${textMuted} text-xs mt-2`}>{t('condition.trend.loading')}</div>
      </section>
    )
  }

  if (error || !hasCcs) {
    return (
      <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
        <h2 className="text-sm font-semibold">{t('condition.trend.title')}</h2>
        <div className={`${textMuted} text-xs mt-2`}>{t('condition.trend.no_data')}</div>
      </section>
    )
  }

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4 space-y-6`}>
      <h2 className="text-sm font-semibold">{t('condition.trend.title')}</h2>

      {/* CCS + 28日移動平均 */}
      <div>
        <div className={`text-xs font-semibold mb-1 ${sectionTitle}`}>
          {t('condition.trend.ccs_section')}
        </div>
        <div style={{ width: '100%', height: 240 }}>
          <ResponsiveContainer>
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
              <XAxis dataKey="date" tick={axisTick} />
              <YAxis domain={[0, 100]} tick={axisTick} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line
                type="monotone"
                dataKey="ccs"
                name={t('condition.trend.ccs_line')}
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="ccs_ma28"
                name={t('condition.trend.ccs_ma28')}
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 因子別 F1〜F5 */}
      <div>
          <div className={`text-xs font-semibold mb-1 ${sectionTitle}`}>
            {t('condition.trend.factors_section')}
          </div>
          <div className={`${textMuted} text-xs mb-2`}>{t('condition.trend.factors_note')}</div>
          <div style={{ width: '100%', height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
                <XAxis dataKey="date" tick={axisTick} />
                <YAxis tick={axisTick} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line
                  type="monotone"
                  dataKey="f1"
                  name={`F1 ${t('condition.factor.F1')}`}
                  stroke="#ef4444"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="f2"
                  name={`F2 ${t('condition.factor.F2')}`}
                  stroke="#f59e0b"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="f3"
                  name={`F3 ${t('condition.factor.F3')}`}
                  stroke="#10b981"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="f4"
                  name={`F4 ${t('condition.factor.F4')}`}
                  stroke="#3b82f6"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="f5"
                  name={`F5 ${t('condition.factor.F5')}`}
                  stroke="#a855f7"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

      {/* 補助指標: データある列のみ */}
      {hasAnyAux && (
        <div>
          <div className={`text-xs font-semibold mb-1 ${sectionTitle}`}>
            {t('condition.trend.aux_section')}
          </div>
          <div className={`${textMuted} text-xs mb-2`}>{t('condition.trend.aux_note')}</div>
          <div style={{ width: '100%', height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
                <XAxis dataKey="date" tick={axisTick} />
                <YAxis yAxisId="kg" orientation="left" tick={axisTick} />
                <YAxis yAxisId="pct" orientation="right" tick={axisTick} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {hasWeight && (
                  <Line
                    yAxisId="kg"
                    type="monotone"
                    dataKey="weight_kg"
                    name={t('condition.trend.metric.weight_kg')}
                    stroke="#3b82f6"
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                )}
                {hasMuscle && (
                  <Line
                    yAxisId="kg"
                    type="monotone"
                    dataKey="muscle_mass_kg"
                    name={t('condition.trend.metric.muscle_mass_kg')}
                    stroke="#10b981"
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                )}
                {hasBodyFat && (
                  <Line
                    yAxisId="pct"
                    type="monotone"
                    dataKey="body_fat_pct"
                    name={t('condition.trend.metric.body_fat_pct')}
                    stroke="#f59e0b"
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </section>
  )
}

export default ConditionTrendChart
