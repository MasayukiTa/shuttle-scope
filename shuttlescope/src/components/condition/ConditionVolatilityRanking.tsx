import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LabelList,
} from 'recharts'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'
import { mean, sampleStd } from '@/utils/stats'

// 変動係数ランキング (coach / analyst 限定)
// 対象列ごとに CV(=SD/Mean) と週次差分 SD を算出し、横棒グラフで並び替える。
// N<5 は除外。

interface Props {
  playerId: number
  isLight: boolean
}

const TARGET_KEYS: Array<keyof ConditionRecord> = [
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

const MIN_N = 5

interface Row {
  key: string
  label: string
  cv: number | null
  diffSd: number | null
  n: number
}

function parseDate(s: string | undefined): number | null {
  if (!s) return null
  const t = Date.parse(s)
  return Number.isFinite(t) ? t : null
}

export function ConditionVolatilityRanking({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading } = useConditions(playerId, { limit: 200 })

  const rows = useMemo<Row[]>(() => {
    const records = Array.isArray(data) ? [...data] : []
    // 日付昇順に並べる (差分計算のため)
    records.sort(
      (a, b) => (parseDate(a.measured_at) ?? 0) - (parseDate(b.measured_at) ?? 0),
    )

    const out: Row[] = []
    for (const key of TARGET_KEYS) {
      const vals: number[] = []
      for (const r of records) {
        const v = (r as unknown as Record<string, unknown>)[key as string]
        if (typeof v === 'number' && Number.isFinite(v)) vals.push(v)
      }
      const n = vals.length
      if (n < MIN_N) continue

      const m = mean(vals)
      const sd = sampleStd(vals)
      let cv: number | null = null
      if (m != null && sd != null && m !== 0 && Number.isFinite(m) && Number.isFinite(sd)) {
        // CV は絶対値で扱う (平均が負の場合でもばらつきの尺度として比較可能にする)
        cv = Math.abs(sd / m)
      }

      // 週次差分 SD: 連続値の1階差分の標本 SD
      const diffs: number[] = []
      for (let i = 1; i < vals.length; i++) {
        diffs.push(vals[i] - vals[i - 1])
      }
      const diffSd = diffs.length >= 2 ? sampleStd(diffs) : null

      out.push({
        key: String(key),
        label: t(`condition.volatility.metric.${String(key)}`),
        cv,
        diffSd,
        n,
      })
    }

    // CV 降順 (null は末尾)
    out.sort((a, b) => {
      const av = a.cv ?? -Infinity
      const bv = b.cv ?? -Infinity
      return bv - av
    })
    return out
  }, [data, t])

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const gridColor = isLight ? '#e5e7eb' : '#374151'
  const tickColor = isLight ? '#374151' : '#9ca3af'

  const cvColor = '#3b82f6'
  const diffColor = '#f59e0b'

  const cvData = rows.map((r) => ({
    label: r.label,
    value: r.cv ?? 0,
    n: r.n,
    raw: r.cv,
  }))
  const diffData = rows.map((r) => ({
    label: r.label,
    value: r.diffSd ?? 0,
    n: r.n,
    raw: r.diffSd,
  }))

  // 棒グラフ高さ = 指標数に応じて伸縮
  const chartHeight = Math.max(200, rows.length * 34 + 40)

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']} fallback={null}>
      <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
        <div className="flex items-baseline justify-between mb-2 flex-wrap gap-2">
          <h2 className="text-sm font-semibold">{t('condition.volatility.title')}</h2>
          <span className={`text-[11px] ${textMuted}`}>
            {t('condition.volatility.description')}
          </span>
        </div>

        {isLoading ? (
          <div className={`${textMuted} text-xs`}>
            {t('condition.volatility.loading')}
          </div>
        ) : rows.length === 0 ? (
          <div className={`${textMuted} text-xs`}>
            {t('condition.volatility.no_data')}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div className={`text-xs mb-1 ${textMuted}`}>
                {t('condition.volatility.cv_axis')}
              </div>
              <div style={{ width: '100%', height: chartHeight }}>
                <ResponsiveContainer>
                  <BarChart
                    data={cvData}
                    layout="vertical"
                    margin={{ top: 8, right: 24, bottom: 8, left: 16 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                    <XAxis
                      type="number"
                      tick={{ fill: tickColor, fontSize: 11 }}
                    />
                    <YAxis
                      type="category"
                      dataKey="label"
                      width={96}
                      tick={{ fill: tickColor, fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: isLight ? '#ffffff' : '#1f2937',
                        border: `1px solid ${gridColor}`,
                        fontSize: 12,
                      }}
                      formatter={(
                        _v: unknown,
                        _n: unknown,
                        entry: { payload?: { raw: number | null; n: number } },
                      ) => {
                        const p = entry?.payload
                        const rv = p && p.raw != null ? p.raw.toFixed(3) : '—'
                        return [
                          `${t('condition.volatility.tooltip_cv')}=${rv}, ${t('condition.volatility.tooltip_n')}=${p?.n ?? 0}`,
                          '',
                        ]
                      }}
                    />
                    <Bar dataKey="value" fill={cvColor}>
                      <LabelList
                        dataKey="raw"
                        position="right"
                        formatter={(v: number | null | undefined) =>
                          v == null ? '—' : v.toFixed(2)
                        }
                        style={{ fill: tickColor, fontSize: 11 }}
                      />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div>
              <div className={`text-xs mb-1 ${textMuted}`}>
                {t('condition.volatility.diff_axis')}
              </div>
              <div style={{ width: '100%', height: chartHeight }}>
                <ResponsiveContainer>
                  <BarChart
                    data={diffData}
                    layout="vertical"
                    margin={{ top: 8, right: 24, bottom: 8, left: 16 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                    <XAxis
                      type="number"
                      tick={{ fill: tickColor, fontSize: 11 }}
                    />
                    <YAxis
                      type="category"
                      dataKey="label"
                      width={96}
                      tick={{ fill: tickColor, fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: isLight ? '#ffffff' : '#1f2937',
                        border: `1px solid ${gridColor}`,
                        fontSize: 12,
                      }}
                      formatter={(
                        _v: unknown,
                        _n: unknown,
                        entry: { payload?: { raw: number | null; n: number } },
                      ) => {
                        const p = entry?.payload
                        const rv = p && p.raw != null ? p.raw.toFixed(3) : '—'
                        return [
                          `${t('condition.volatility.tooltip_diff')}=${rv}, ${t('condition.volatility.tooltip_n')}=${p?.n ?? 0}`,
                          '',
                        ]
                      }}
                    />
                    <Bar dataKey="value" fill={diffColor}>
                      <LabelList
                        dataKey="raw"
                        position="right"
                        formatter={(v: number | null | undefined) =>
                          v == null ? '—' : v.toFixed(2)
                        }
                        style={{ fill: tickColor, fontSize: 11 }}
                      />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </section>
    </RoleGuard>
  )
}

export default ConditionVolatilityRanking
