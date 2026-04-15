import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { useAuth } from '@/hooks/useAuth'
import { useConditions, ConditionRecord } from '@/hooks/useConditions'
import { mean } from '@/utils/stats'

// 季節性・曜日効果コンポーネント (coach / analyst 限定)
// 月次 / 四半期 / 曜日別に各指標の平均を集計して表示する。

interface Props {
  playerId: number
  isLight: boolean
}

type ViewMode = 'month' | 'quarter' | 'dow'

// 表示対象の指標キー (ConditionRecord 上の field name と一致)
const METRIC_KEYS = [
  'ccs',
  'f1',
  'f2',
  'f3',
  'f4',
  'f5',
  'hooper_index',
  'sleep_hours',
] as const
type MetricKey = (typeof METRIC_KEYS)[number]

const MIN_N = 3
const PRIMARY_COLOR = '#3b82f6'

function getMetric(rec: ConditionRecord, key: MetricKey): number | null {
  const v = (rec as unknown as Record<string, unknown>)[key]
  if (v == null) return null
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return v
}

function parseLocalDate(s: string | undefined): Date | null {
  if (!s) return null
  const t = Date.parse(s)
  if (!Number.isFinite(t)) return null
  return new Date(t)
}

// 指標ごとの存在可否 (= 有効値が 1 件以上存在するか)
function detectAvailableMetrics(records: ConditionRecord[]): MetricKey[] {
  const out: MetricKey[] = []
  for (const k of METRIC_KEYS) {
    let found = false
    for (const r of records) {
      if (getMetric(r, k) != null) {
        found = true
        break
      }
    }
    if (found) out.push(k)
  }
  return out
}

interface Bucket {
  label: string
  values: Partial<Record<MetricKey, number[]>>
}

function bucketize(
  records: ConditionRecord[],
  mode: ViewMode,
  metrics: MetricKey[],
  t: (k: string, opts?: Record<string, unknown>) => string,
): Bucket[] {
  let size = 12
  if (mode === 'quarter') size = 4
  if (mode === 'dow') size = 7

  const buckets: Bucket[] = Array.from({ length: size }, (_, i) => {
    let label = ''
    if (mode === 'month') label = t('condition.seasonality.month_label', { n: i + 1 })
    else if (mode === 'quarter') label = `Q${i + 1}`
    else label = t(`condition.seasonality.dow.${i}`)
    const values: Partial<Record<MetricKey, number[]>> = {}
    for (const k of metrics) values[k] = []
    return { label, values }
  })

  for (const rec of records) {
    const d = parseLocalDate(rec.measured_at)
    if (!d) continue
    let idx = 0
    if (mode === 'month') idx = d.getMonth() // 0-11
    else if (mode === 'quarter') idx = Math.floor(d.getMonth() / 3) // 0-3
    else {
      // getDay(): 0=Sun..6=Sat → 月始まりに変換 (0=Mon..6=Sun)
      const dow = d.getDay()
      idx = dow === 0 ? 6 : dow - 1
    }
    for (const k of metrics) {
      const v = getMetric(rec, k)
      if (v == null) continue
      buckets[idx].values[k]!.push(v)
    }
  }

  return buckets
}

export function ConditionSeasonality({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { data, isLoading, error } = useConditions(playerId, { limit: 200 })
  const [mode, setMode] = useState<ViewMode>('month')
  const [metric, setMetric] = useState<MetricKey>('ccs')

  // 二重防御: player には何も描画しない
  if (role !== 'coach' && role !== 'analyst') return null

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const muted = isLight ? 'text-gray-500' : 'text-gray-400'
  const headBg = isLight ? 'bg-gray-50' : 'bg-gray-900/60'
  const activeBtn = 'bg-blue-500 text-white border-blue-500'
  const inactiveBtn = isLight
    ? 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
    : 'bg-gray-800 text-gray-200 border-gray-600 hover:bg-gray-700'

  const records = useMemo(() => (data ?? []).slice(), [data])
  const availableMetrics = useMemo(() => detectAvailableMetrics(records), [records])

  // 現在選択中の指標が存在しなければ先頭に差し替える
  const effectiveMetric: MetricKey =
    availableMetrics.includes(metric) ? metric : availableMetrics[0] ?? 'ccs'

  const buckets = useMemo(
    () => bucketize(records, mode, availableMetrics.length ? availableMetrics : ['ccs'], t),
    [records, mode, availableMetrics, t],
  )

  // チャート用データ (選択指標のみ)
  const chartData = useMemo(
    () =>
      buckets.map((b) => {
        const arr = b.values[effectiveMetric] ?? []
        const n = arr.length
        const m = n >= MIN_N ? mean(arr) : null
        return {
          label: b.label,
          n,
          value: m,
        }
      }),
    [buckets, effectiveMetric],
  )

  const hasAnyData = records.length > 0

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-baseline justify-between mb-2 gap-2 flex-wrap">
        <h2 className="text-sm font-semibold">{t('condition.seasonality.title')}</h2>
        <span className={`text-[11px] ${muted}`}>
          {t('condition.seasonality.description')}
        </span>
      </div>

      {/* モード切替 */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {(['month', 'quarter', 'dow'] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`text-xs px-2 py-1 border rounded ${
              mode === m ? activeBtn : inactiveBtn
            }`}
          >
            {t(`condition.seasonality.mode.${m}`)}
          </button>
        ))}
      </div>

      {/* 指標切替 */}
      {availableMetrics.length > 1 && (
        <div className="flex gap-1 mb-3 flex-wrap">
          {availableMetrics.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setMetric(k)}
              className={`text-[11px] px-2 py-0.5 border rounded ${
                effectiveMetric === k ? activeBtn : inactiveBtn
              }`}
            >
              {t(`condition.seasonality.metric.${k}`)}
            </button>
          ))}
        </div>
      )}

      {isLoading ? (
        <div className={`${muted} text-xs`}>{t('condition.seasonality.loading')}</div>
      ) : error ? (
        <div className={`${muted} text-xs`}>{t('condition.seasonality.no_data')}</div>
      ) : !hasAnyData ? (
        <div className={`${muted} text-xs`}>{t('condition.seasonality.no_data')}</div>
      ) : (
        <>
          <div className="w-full" style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke={isLight ? '#e5e7eb' : '#374151'}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: isLight ? '#374151' : '#d1d5db' }}
                />
                <YAxis tick={{ fontSize: 11, fill: isLight ? '#374151' : '#d1d5db' }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: isLight ? '#ffffff' : '#1f2937',
                    border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
                    fontSize: 12,
                  }}
                  formatter={(v: unknown, _name, payload) => {
                    const n = (payload?.payload as { n?: number } | undefined)?.n ?? 0
                    if (v == null) return ['—', t('condition.seasonality.col_mean')]
                    return [
                      `${(v as number).toFixed(2)} (N=${n})`,
                      t('condition.seasonality.col_mean'),
                    ]
                  }}
                />
                <Bar dataKey="value" fill={PRIMARY_COLOR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* 補助テーブル: 全指標の平均と N */}
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-xs">
              <thead className={headBg}>
                <tr>
                  <th className="text-left px-2 py-1 font-medium">
                    {t('condition.seasonality.col_bucket')}
                  </th>
                  {availableMetrics.map((k) => (
                    <th key={k} className="text-right px-2 py-1 font-medium">
                      {t(`condition.seasonality.metric.${k}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {buckets.map((b, i) => (
                  <tr key={i} className={`border-t ${borderColor}`}>
                    <td className="px-2 py-1">{b.label}</td>
                    {availableMetrics.map((k) => {
                      const arr = b.values[k] ?? []
                      const n = arr.length
                      const m = n >= MIN_N ? mean(arr) : null
                      return (
                        <td key={k} className="px-2 py-1 text-right font-mono">
                          {m == null ? (
                            <span className={muted}>
                              {t('condition.seasonality.no_value')}
                              <span className="ml-1">(N={n})</span>
                            </span>
                          ) : (
                            <>
                              {m.toFixed(2)}
                              <span className={`ml-1 ${muted}`}>(N={n})</span>
                            </>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={`${muted} text-[11px] mt-2`}>
            {t('condition.seasonality.min_n_note', { n: MIN_N })}
          </div>
        </>
      )}
    </section>
  )
}

export default ConditionSeasonality
