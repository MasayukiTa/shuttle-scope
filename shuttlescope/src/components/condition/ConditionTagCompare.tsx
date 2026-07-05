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
import {
  useConditionTags,
  isDateInTag,
  type ConditionTag,
} from '@/hooks/useConditionTags'

// coach / analyst 限定:
// 期間タグを選択→ 期間内 vs 期間外 で各指標の平均差分を棒グラフで比較。
// サンプル数 N を必ず併記し、片側 N<2 の指標は差分を出さず注記する。
interface Props {
  playerId: number
  isLight: boolean
}

// 比較対象の指標キー（ccs_score は ConditionRecord 型には含まれないため any で読む）
const METRIC_KEYS = [
  'ccs_score',
  'hooper_sleep',
  'hooper_soreness',
  'hooper_stress',
  'hooper_fatigue',
  'session_rpe',
  'sleep_hours',
  'weight_kg',
  'muscle_mass_kg',
  'body_fat_pct',
] as const

type MetricKey = (typeof METRIC_KEYS)[number]

interface RowStats {
  key: MetricKey
  label: string
  inMean: number | null
  outMean: number | null
  diff: number | null   // inMean - outMean
  nIn: number
  nOut: number
}

function mean(values: number[]): number | null {
  if (values.length === 0) return null
  return values.reduce((a, b) => a + b, 0) / values.length
}

export function ConditionTagCompare({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data: tags = [] } = useConditionTags(playerId)
  const { data: conditions = [] } = useConditions(playerId, { limit: 1000 })

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selectedTag: ConditionTag | undefined = useMemo(
    () => tags.find((t) => t.id === selectedId),
    [tags, selectedId],
  )

  const stats: RowStats[] = useMemo(() => {
    if (!selectedTag) return []
    const inside: ConditionRecord[] = []
    const outside: ConditionRecord[] = []
    for (const c of conditions) {
      if (!c.measured_at) continue
      if (isDateInTag(c.measured_at, selectedTag)) inside.push(c)
      else outside.push(c)
    }
    return METRIC_KEYS.map((k) => {
      const getVal = (c: ConditionRecord): number | null => {
        // ccs_score は ConditionRecord に明示列が無いので any 経由で読む
        const v = (c as unknown as Record<string, unknown>)[k]
        return typeof v === 'number' && Number.isFinite(v) ? v : null
      }
      const inVals = inside.map(getVal).filter((v): v is number => v != null)
      const outVals = outside.map(getVal).filter((v): v is number => v != null)
      const inM = mean(inVals)
      const outM = mean(outVals)
      const diff = inM != null && outM != null ? inM - outM : null
      return {
        key: k,
        label: t(`condition.tags.metrics.${k}`),
        inMean: inM,
        outMean: outM,
        diff,
        nIn: inVals.length,
        nOut: outVals.length,
      }
    })
  }, [conditions, selectedTag, t])

  const chartData = useMemo(
    () =>
      stats
        .filter((s) => s.diff != null && s.nIn >= 2 && s.nOut >= 2)
        .map((s) => ({
          key: s.key,
          label: s.label,
          diff: s.diff as number,
          nIn: s.nIn,
          nOut: s.nOut,
        })),
    [stats],
  )

  const cardCls = 'border border-[var(--ss-border)] bg-[var(--ss-surface-1)] rounded-ss-lg p-3'
  const labelCls = 'text-xs text-[var(--ss-t2)]'
  const selectCls = 'border border-[var(--ss-border-strong)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] rounded-ss-md px-2 py-1.5 text-base'

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="space-y-3">
        <div>
          <h3 className={'text-sm font-semibold text-[var(--ss-t1)]'}>
            {t('condition.tags.compare_title')}
          </h3>
          <p className={labelCls}>{t('condition.tags.compare_description')}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className={labelCls}>{t('condition.tags.select_tag')}</label>
          <select
            className={selectCls}
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">{t('condition.tags.none_selected')}</option>
            {tags.map((tg) => (
              <option key={tg.id} value={tg.id}>
                {tg.label} ({tg.start_date}
                {tg.end_date ? ` - ${tg.end_date}` : ''})
              </option>
            ))}
          </select>
        </div>

        {!selectedTag && (
          <div className={cardCls + ' ' + labelCls}>
            {t('condition.tags.no_tag_hint')}
          </div>
        )}

        {selectedTag && (
          <>
            <div className={cardCls}>
              {chartData.length === 0 ? (
                <div className={labelCls}>{t('condition.tags.insufficient_sample')}</div>
              ) : (
                <div style={{ width: '100%', height: 300 }}>
                  <ResponsiveContainer>
                    <BarChart
                      data={chartData}
                      margin={{ top: 8, right: 12, left: 4, bottom: 40 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke={'var(--ss-border)'} />
                      <XAxis
                        dataKey="label"
                        angle={-25}
                        textAnchor="end"
                        height={60}
                        tick={{ fontSize: 11, fill: 'var(--ss-t2)' }}
                      />
                      <YAxis tick={{ fontSize: 11, fill: 'var(--ss-t2)' }} />
                      <Tooltip
                        formatter={(v: number, _n, item: { payload?: { nIn: number; nOut: number } }) => {
                          const p = item?.payload
                          const n = p ? ` (N_in=${p.nIn}, N_out=${p.nOut})` : ''
                          return [`${v.toFixed(2)}${n}`, t('condition.tags.diff_label')]
                        }}
                        contentStyle={{
                          backgroundColor: 'var(--ss-surface-1)',
                          border: `1px solid var(--ss-border-strong)`,
                          color: 'var(--ss-t1)',
                        }}
                      />
                      <ReferenceLine y={0} stroke={'var(--ss-border-strong)'} />
                      <Bar dataKey="diff">
                        {chartData.map((d, idx) => (
                          <Cell
                            key={idx}
                            fill={d.diff >= 0 ? selectedTag.color : 'var(--ss-bad)'}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* 数値テーブル（N 併記） */}
            <div className={cardCls + ' overflow-x-auto'}>
              <table className="w-full text-xs">
                <thead>
                  <tr className={'text-[var(--ss-t2)]'}>
                    <th className="text-left py-1 pr-2">{t('condition.tags.metric')}</th>
                    <th className="text-right py-1 px-2">{t('condition.tags.in_mean')}</th>
                    <th className="text-right py-1 px-2">{t('condition.tags.out_mean')}</th>
                    <th className="text-right py-1 px-2">{t('condition.tags.diff_label')}</th>
                    <th className="text-right py-1 px-2">{t('auto.ConditionTagCompare.n_in')}<sub>{t('auto.ConditionTagCompare.in')}</sub></th>
                    <th className="text-right py-1 px-2">{t('auto.ConditionTagCompare.n_in')}<sub>{t('auto.ConditionTagCompare.out')}</sub></th>
                  </tr>
                </thead>
                <tbody className={'text-[var(--ss-t1)]'}>
                  {stats.map((s) => {
                    const insufficient = s.nIn < 2 || s.nOut < 2
                    return (
                      <tr key={s.key} className="border-t border-[var(--ss-border)]">
                        <td className="py-1 pr-2">{s.label}</td>
                        <td className="text-right py-1 px-2 num-cell ss-num">
                          {s.inMean != null ? s.inMean.toFixed(2) : '—'}
                        </td>
                        <td className="text-right py-1 px-2 num-cell ss-num">
                          {s.outMean != null ? s.outMean.toFixed(2) : '—'}
                        </td>
                        <td className="text-right py-1 px-2 num-cell ss-num">
                          {insufficient || s.diff == null ? (
                            <span className="opacity-60">
                              {t('condition.tags.insufficient_short')}
                            </span>
                          ) : (
                            s.diff.toFixed(2)
                          )}
                        </td>
                        <td className="text-right py-1 px-2 num-cell ss-num">{s.nIn}</td>
                        <td className="text-right py-1 px-2 num-cell ss-num">{s.nOut}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p className={labelCls + ' mt-2'}>{t('condition.tags.sample_note')}</p>
            </div>
          </>
        )}
      </div>
    </RoleGuard>
  )
}
