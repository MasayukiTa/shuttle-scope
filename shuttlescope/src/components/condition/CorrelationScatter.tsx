import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useCorrelation } from '@/hooks/useConditionAnalytics'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { catColor } from '@/styles/categoricalPalette'

// 相関散布図（coach/analyst 専用）
// x/y: コンディション指標または試合指標キー
interface Props {
  playerId: number
  isLight: boolean
}

const METRIC_OPTIONS: Array<{ value: string; key: string }> = [
  { value: 'ccs', key: 'ccs' },
  { value: 'muscle_mass_kg', key: 'muscle' },
  { value: 'body_fat_pct', key: 'body_fat' },
  { value: 'hooper_index', key: 'hooper' },
  { value: 'session_rpe', key: 'rpe' },
  { value: 'sleep_hours', key: 'sleep' },
  { value: 'match_win_rate', key: 'win_rate' },
  { value: 'match_performance', key: 'performance' },
]

export function CorrelationScatter({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const [x, setX] = useState<string>('muscle_mass_kg')
  const [y, setY] = useState<string>('match_win_rate')

  const { data, isLoading, error } = useCorrelation(playerId, x, y)

  const panelBg = 'bg-[var(--ss-surface-1)]'
  const borderColor = 'border-[var(--ss-border)]'
  const textMuted = 'text-[var(--ss-t3)]'
  const selectCls = 'border border-[var(--ss-border-strong)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] rounded-ss-md px-2 py-1 text-sm'

  const points = data?.points ?? []
  const n = data?.n ?? 0
  const r = data?.pearson_r
  const p = data?.p_value

  return (
    <section className={`rounded-ss-lg border ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-[var(--ss-t1)]">{t('condition.correlation.title')}</h2>
        {n > 0 && <ConfidenceBadge sampleSize={n} />}
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex items-center gap-2">
          <label className={`text-xs ${textMuted}`}>{t('condition.correlation.x_axis')}</label>
          <select className={selectCls} value={x} onChange={(e) => setX(e.target.value)}>
            {METRIC_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {t(`condition.correlation.metric.${o.key}`)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className={`text-xs ${textMuted}`}>{t('condition.correlation.y_axis')}</label>
          <select className={selectCls} value={y} onChange={(e) => setY(e.target.value)}>
            {METRIC_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {t(`condition.correlation.metric.${o.key}`)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.correlation.loading')}</div>
      ) : error ? (
        <div className={`${textMuted} text-xs`}>{t('condition.correlation.no_data')}</div>
      ) : points.length === 0 ? (
        <div className={`${textMuted} text-xs`}>{t('condition.correlation.no_data')}</div>
      ) : (
        <>
          <div style={{ width: '100%', height: 280 }}>
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={'var(--ss-border)'} />
                <XAxis
                  type="number"
                  dataKey="x"
                  name={x}
                  tick={{ fill: 'var(--ss-t3)', fontSize: 11 }}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  name={y}
                  tick={{ fill: 'var(--ss-t3)', fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--ss-surface-1)',
                    border: `1px solid var(--ss-border)`,
                    fontSize: 12,
                    borderRadius: 6,
                  }}
                />
                <Scatter data={points} fill={catColor('Cool', isLight)} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className={`mt-3 flex flex-wrap gap-4 text-xs ${textMuted}`}>
            <span>
              {t('condition.correlation.pearson_r')}:{' '}
              <span className="font-mono ss-num">{r != null ? r.toFixed(3) : '—'}</span>
            </span>
            <span>
              {t('auto.CorrelationScatter.n_label')} <span className="font-mono ss-num">{n}</span>
            </span>
            <span>
              {t('condition.correlation.p_value')}:{' '}
              <span className="font-mono ss-num">{p != null ? p.toFixed(3) : '—'}</span>
            </span>
            {data?.confidence_note && <span className="italic">{data.confidence_note}</span>}
          </div>
        </>
      )}
    </section>
  )
}
