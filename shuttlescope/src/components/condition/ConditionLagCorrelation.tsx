import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'
import { pearson } from '@/utils/stats'

// ラグ相関（Lead/Lag）コンポーネント
// X(t) と Y(t+k) の Pearson 相関を k=-4..+4 週で算出して棒グラフ表示
// coach / analyst 限定

interface Props {
  playerId: number
  isLight: boolean
}

// 対象となる可能性のある列（UIに表示するのは実際に値が入っているものに限定）
const CANDIDATE_KEYS: Array<keyof ConditionRecord> = [
  'hooper_sleep',
  'hooper_soreness',
  'hooper_stress',
  'hooper_fatigue',
  'session_rpe',
  'sleep_hours',
  'weight_kg',
  'muscle_mass_kg',
  'body_fat_pct',
]

const LAGS = [-4, -3, -2, -1, 0, 1, 2, 3, 4]
const MIN_N = 5

// measured_at (YYYY-MM-DD) から ISO 週番号ベースのインデックスを返す
function weekIndex(dateStr: string): number {
  const d = new Date(dateStr + 'T00:00:00Z')
  if (Number.isNaN(d.getTime())) return NaN
  // エポックからの週数（UTC 基準）
  const days = Math.floor(d.getTime() / 86400000)
  return Math.floor(days / 7)
}

export function ConditionLagCorrelation({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading } = useConditions(playerId, { limit: 200 })

  const records: ConditionRecord[] = useMemo(() => {
    const list = Array.isArray(data) ? [...data] : []
    list.sort((a, b) => {
      const da = a.measured_at ?? ''
      const db = b.measured_at ?? ''
      return da.localeCompare(db)
    })
    return list
  }, [data])

  // 利用可能な列（少なくとも1件 数値がある）を抽出
  const availableKeys = useMemo(() => {
    return CANDIDATE_KEYS.filter((k) =>
      records.some((r) => {
        const v = r[k] as unknown
        return typeof v === 'number' && Number.isFinite(v)
      }),
    )
  }, [records])

  const [x, setX] = useState<string>('')
  const [y, setY] = useState<string>('')

  // 初期選択
  const effectiveX = x || availableKeys[0] || ''
  const effectiveY = y || availableKeys[1] || availableKeys[0] || ''

  // 週次シリーズ（同週は平均）
  const weekly = useMemo(() => {
    const map = new Map<
      number,
      { xSum: number; xN: number; ySum: number; yN: number }
    >()
    for (const r of records) {
      if (!r.measured_at) continue
      const wi = weekIndex(r.measured_at)
      if (!Number.isFinite(wi)) continue
      const xv = r[effectiveX as keyof ConditionRecord] as unknown
      const yv = r[effectiveY as keyof ConditionRecord] as unknown
      const entry = map.get(wi) ?? { xSum: 0, xN: 0, ySum: 0, yN: 0 }
      if (typeof xv === 'number' && Number.isFinite(xv)) {
        entry.xSum += xv
        entry.xN += 1
      }
      if (typeof yv === 'number' && Number.isFinite(yv)) {
        entry.ySum += yv
        entry.yN += 1
      }
      map.set(wi, entry)
    }
    if (map.size === 0) return { weeks: [] as number[], xs: [] as number[], ys: [] as number[] }
    const minW = Math.min(...map.keys())
    const maxW = Math.max(...map.keys())
    const weeks: number[] = []
    const xs: number[] = []
    const ys: number[] = []
    for (let w = minW; w <= maxW; w++) {
      weeks.push(w)
      const e = map.get(w)
      xs.push(e && e.xN > 0 ? e.xSum / e.xN : NaN)
      ys.push(e && e.yN > 0 ? e.ySum / e.yN : NaN)
    }
    return { weeks, xs, ys }
  }, [records, effectiveX, effectiveY])

  // 各ラグで相関を計算
  const lagResults = useMemo(() => {
    const { xs, ys } = weekly
    return LAGS.map((k) => {
      const pairX: number[] = []
      const pairY: number[] = []
      for (let i = 0; i < xs.length; i++) {
        const j = i + k
        if (j < 0 || j >= ys.length) continue
        const xv = xs[i]
        const yv = ys[j]
        if (!Number.isFinite(xv) || !Number.isFinite(yv)) continue
        pairX.push(xv)
        pairY.push(yv)
      }
      const n = pairX.length
      const r = n >= MIN_N ? pearson(pairX, pairY) : null
      return { lag: k, n, r }
    })
  }, [weekly])

  const bestLag = useMemo(() => {
    let best: { lag: number; n: number; r: number } | null = null
    for (const row of lagResults) {
      if (row.r == null) continue
      if (!best || Math.abs(row.r) > Math.abs(best.r)) {
        best = { lag: row.lag, n: row.n, r: row.r }
      }
    }
    return best
  }, [lagResults])

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const selectCls = isLight
    ? 'border border-gray-300 bg-white text-gray-900 rounded px-2 py-1 text-sm'
    : 'border border-gray-600 bg-gray-800 text-white rounded px-2 py-1 text-sm'

  const chartData = lagResults.map((row) => ({
    lag: row.lag,
    r: row.r,
    n: row.n,
    rValue: row.r ?? 0,
  }))

  const posColor = '#3b82f6'
  const negColor = '#ef4444'
  const highlightColor = '#f59e0b'

  const hasAny = lagResults.some((row) => row.r != null)

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']} fallback={null}>
      <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-sm font-semibold">{t('condition.lag_corr.title')}</h2>
        </div>

        <p className={`text-xs ${textMuted} mb-3`}>{t('condition.lag_corr.description')}</p>

        <div className="flex flex-wrap items-center gap-3 mb-4">
          <div className="flex items-center gap-2">
            <label className={`text-xs ${textMuted}`}>{t('condition.lag_corr.x_label')}</label>
            <select
              className={selectCls}
              value={effectiveX}
              onChange={(e) => setX(e.target.value)}
            >
              {availableKeys.map((k) => (
                <option key={k} value={k}>
                  {t(`condition.lag_corr.metric.${k}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className={`text-xs ${textMuted}`}>{t('condition.lag_corr.y_label')}</label>
            <select
              className={selectCls}
              value={effectiveY}
              onChange={(e) => setY(e.target.value)}
            >
              {availableKeys.map((k) => (
                <option key={k} value={k}>
                  {t(`condition.lag_corr.metric.${k}`)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {isLoading ? (
          <div className={`${textMuted} text-xs`}>…</div>
        ) : availableKeys.length < 1 || !hasAny ? (
          <div className={`${textMuted} text-xs`}>{t('condition.lag_corr.no_data')}</div>
        ) : (
          <>
            <div style={{ width: '100%', height: 280 }}>
              <ResponsiveContainer>
                <BarChart
                  data={chartData}
                  margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={isLight ? '#e5e7eb' : '#374151'}
                  />
                  <XAxis
                    dataKey="lag"
                    tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 11 }}
                    label={{
                      value: t('condition.lag_corr.lag_axis'),
                      position: 'insideBottom',
                      offset: -4,
                      fill: isLight ? '#374151' : '#9ca3af',
                      fontSize: 11,
                    }}
                  />
                  <YAxis
                    type="number"
                    domain={[-1, 1]}
                    tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 11 }}
                  />
                  <ReferenceLine y={0} stroke={isLight ? '#9ca3af' : '#6b7280'} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: isLight ? '#ffffff' : '#1f2937',
                      border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
                      fontSize: 12,
                    }}
                    formatter={(_value: unknown, _name: unknown, entry: { payload?: { r: number | null; n: number } }) => {
                      const p = entry?.payload
                      const rStr = p && p.r != null ? p.r.toFixed(3) : t('condition.lag_corr.insufficient')
                      return [
                        `${t('condition.lag_corr.tooltip_r')}=${rStr}, ${t('condition.lag_corr.tooltip_n')}=${p?.n ?? 0}`,
                        '',
                      ]
                    }}
                    labelFormatter={(label: number) =>
                      `${t('condition.lag_corr.lag_axis')}: ${label} ${t('condition.lag_corr.weeks')}`
                    }
                  />
                  <Bar dataKey="rValue">
                    {chartData.map((d, i) => {
                      const isBest = bestLag != null && bestLag.lag === d.lag
                      const color =
                        d.r == null
                          ? isLight
                            ? '#d1d5db'
                            : '#4b5563'
                          : isBest
                            ? highlightColor
                            : d.r >= 0
                              ? posColor
                              : negColor
                      return <Cell key={i} fill={color} />
                    })}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className={`mt-2 flex flex-wrap items-center gap-3 text-[11px] ${textMuted}`}>
              <span className="inline-flex items-center gap-1">
                <span style={{ width: 10, height: 10, background: posColor, display: 'inline-block', borderRadius: 2 }} />
                {t('condition.lag_corr.legend_pos')}
              </span>
              <span className="inline-flex items-center gap-1">
                <span style={{ width: 10, height: 10, background: negColor, display: 'inline-block', borderRadius: 2 }} />
                {t('condition.lag_corr.legend_neg')}
              </span>
              <span className="inline-flex items-center gap-1">
                <span style={{ width: 10, height: 10, background: highlightColor, display: 'inline-block', borderRadius: 2 }} />
                {t('condition.lag_corr.legend_best')}
              </span>
            </div>
            <div className={`mt-2 flex flex-wrap gap-4 text-xs ${textMuted}`}>
              <span>
                {t('condition.lag_corr.best_lag')}:{' '}
                <span className="font-mono">
                  {bestLag
                    ? `${bestLag.lag} ${t('condition.lag_corr.weeks')} (r=${bestLag.r.toFixed(3)}, N=${bestLag.n})`
                    : t('condition.lag_corr.insufficient')}
                </span>
              </span>
            </div>
          </>
        )}
      </section>
    </RoleGuard>
  )
}

export default ConditionLagCorrelation
