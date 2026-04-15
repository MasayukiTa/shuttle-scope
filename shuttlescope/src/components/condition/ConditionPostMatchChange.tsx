import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
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
import { apiGet } from '@/api/client'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'
import type { Match } from '@/types'

// 試合前後の体調変化（coach/analyst 限定）
// 各試合日の前7日・後7日の平均を計算し、差分を棒グラフで可視化する

interface Props {
  playerId: number
  isLight: boolean
}

// 可視化する体調メトリクス候補。ConditionRecord にない列 (ccs/f1-f5) は
// バックエンドが付加的に返す可能性があるため、動的参照 + 型ガードで扱う。
const METRIC_KEYS = ['ccs', 'f1', 'f2', 'f3', 'f4', 'f5', 'hooper_index'] as const
type MetricKey = (typeof METRIC_KEYS)[number]

const WINDOW_DAYS = 7
const MS_PER_DAY = 86400000

function toTime(dateStr?: string): number | null {
  if (!dateStr) return null
  const t = new Date(dateStr + 'T00:00:00Z').getTime()
  return Number.isFinite(t) ? t : null
}

function pickNumber(rec: ConditionRecord, key: MetricKey): number | null {
  const v = (rec as unknown as Record<string, unknown>)[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  const s = values.reduce((a, b) => a + b, 0)
  return s / values.length
}

export function ConditionPostMatchChange({ playerId, isLight }: Props) {
  const { t } = useTranslation()

  // 試合一覧（当該選手）
  const { data: matchesResp, isLoading: matchesLoading } = useQuery({
    queryKey: ['matches', 'post-match-change', playerId],
    queryFn: () =>
      apiGet<{ success: boolean; data: Match[] }>('/matches', {
        player_id: playerId,
      }),
    enabled: !!playerId,
    retry: 0,
  })

  // 体調履歴
  const { data: conditionsData, isLoading: condLoading } = useConditions(playerId, {
    limit: 200,
  })

  const records = useMemo<ConditionRecord[]>(
    () => (Array.isArray(conditionsData) ? conditionsData : []),
    [conditionsData],
  )

  const matches = useMemo<Match[]>(() => {
    const list = matchesResp?.data ?? []
    return [...list].sort((a, b) => (a.date ?? '').localeCompare(b.date ?? ''))
  }, [matchesResp])

  // 各試合 × メトリクスの前後平均・差分
  const rows = useMemo(() => {
    return matches
      .map((m) => {
        const matchT = toTime(m.date)
        if (matchT == null) return null
        const beforeStart = matchT - WINDOW_DAYS * MS_PER_DAY
        const afterEnd = matchT + WINDOW_DAYS * MS_PER_DAY

        // 前後のレコード集合
        const before: ConditionRecord[] = []
        const after: ConditionRecord[] = []
        for (const r of records) {
          const rt = toTime(r.measured_at)
          if (rt == null) continue
          if (rt >= beforeStart && rt < matchT) before.push(r)
          else if (rt > matchT && rt <= afterEnd) after.push(r)
        }

        const metrics = METRIC_KEYS.map((k) => {
          const bv = before
            .map((r) => pickNumber(r, k))
            .filter((x): x is number => x != null)
          const av = after
            .map((r) => pickNumber(r, k))
            .filter((x): x is number => x != null)
          const bMean = average(bv)
          const aMean = average(av)
          const delta = bMean != null && aMean != null ? aMean - bMean : null
          return { key: k, bN: bv.length, aN: av.length, bMean, aMean, delta }
        }).filter((mrow) => mrow.delta != null)

        return {
          match: m,
          beforeN: before.length,
          afterN: after.length,
          metrics,
        }
      })
      .filter((x): x is NonNullable<typeof x> => x != null)
  }, [matches, records])

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const textBase = isLight ? 'text-gray-900' : 'text-gray-100'

  // プロジェクト色規約: 良い=青, 悪い=赤
  const posColor = '#3b82f6'
  const negColor = '#ef4444'

  // 展開/試合選択 UI state
  const [expanded, setExpanded] = useState(false)
  const [selectedMatchId, setSelectedMatchId] = useState<number | 'all' | null>(null)

  const isLoading = matchesLoading || condLoading

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']} fallback={null}>
      <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="w-full flex items-center justify-between gap-2 mb-1 text-left"
        >
          <div className="flex items-center gap-2">
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            <h2 className={`text-sm font-semibold ${textBase}`}>
              {t('condition.post_match.title')}
            </h2>
          </div>
          <span className={`text-[11px] ${textMuted}`}>
            {expanded ? t('condition.post_match.collapse') : t('condition.post_match.expand')}
          </span>
        </button>
        {expanded && (
          <p className={`text-xs ${textMuted} mt-1 mb-3`}>
            {t('condition.post_match.description')}
          </p>
        )}

        {!expanded ? null : isLoading ? (
          <div className={`${textMuted} text-xs`}>…</div>
        ) : matches.length === 0 ? (
          <div className={`${textMuted} text-xs`}>
            {t('condition.post_match.no_matches')}
          </div>
        ) : rows.length === 0 || rows.every((r) => r.metrics.length === 0) ? (
          <div className={`${textMuted} text-xs`}>
            {t('condition.post_match.no_data')}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <label className={`text-xs ${textMuted}`}>
                {t('condition.post_match.select_match')}
              </label>
              <select
                className={
                  isLight
                    ? 'border border-gray-300 bg-white text-gray-900 rounded px-2 py-1 text-xs'
                    : 'border border-gray-600 bg-gray-800 text-white rounded px-2 py-1 text-xs'
                }
                value={selectedMatchId == null ? '' : String(selectedMatchId)}
                onChange={(e) => {
                  const v = e.target.value
                  if (v === '') setSelectedMatchId(null)
                  else if (v === 'all') setSelectedMatchId('all')
                  else setSelectedMatchId(Number(v))
                }}
              >
                <option value="">{t('condition.post_match.not_selected')}</option>
                <option value="all">{t('condition.post_match.all_matches')}</option>
                {rows.map((row) => (
                  <option key={row.match.id} value={row.match.id}>
                    {row.match.date}
                    {row.match.tournament ? `（${row.match.tournament}）` : ''}
                  </option>
                ))}
              </select>
            </div>
            {selectedMatchId == null ? (
              <div className={`${textMuted} text-xs`}>
                {t('condition.post_match.hint_select')}
              </div>
            ) : (rows
              .filter((row) => selectedMatchId === 'all' || row.match.id === selectedMatchId)
            ).map((row) => {
              if (row.metrics.length === 0) return null
              const chartData = row.metrics.map((mrow) => ({
                metric: t(`condition.post_match.metric.${mrow.key}`),
                delta: mrow.delta as number,
                bMean: mrow.bMean,
                aMean: mrow.aMean,
                bN: mrow.bN,
                aN: mrow.aN,
              }))
              return (
                <div
                  key={row.match.id}
                  className={`rounded border ${borderColor} p-3`}
                >
                  <div
                    className={`flex flex-wrap items-baseline justify-between gap-2 mb-2`}
                  >
                    <div className={`text-xs font-medium ${textBase}`}>
                      {t('condition.post_match.match_label', {
                        date: row.match.date,
                        tournament: row.match.tournament ?? '',
                      })}
                    </div>
                    <div className={`text-[11px] ${textMuted}`}>
                      {t('condition.post_match.sample_note', {
                        before: row.beforeN,
                        after: row.afterN,
                      })}
                    </div>
                  </div>

                  <div style={{ width: '100%', height: 180 }}>
                    <ResponsiveContainer>
                      <BarChart
                        data={chartData}
                        margin={{ top: 4, right: 12, bottom: 4, left: 0 }}
                      >
                        <CartesianGrid
                          strokeDasharray="3 3"
                          stroke={isLight ? '#e5e7eb' : '#374151'}
                        />
                        <XAxis
                          dataKey="metric"
                          tick={{
                            fill: isLight ? '#374151' : '#9ca3af',
                            fontSize: 11,
                          }}
                        />
                        <YAxis
                          tick={{
                            fill: isLight ? '#374151' : '#9ca3af',
                            fontSize: 11,
                          }}
                        />
                        <ReferenceLine
                          y={0}
                          stroke={isLight ? '#9ca3af' : '#6b7280'}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: isLight ? '#ffffff' : '#1f2937',
                            border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
                            fontSize: 12,
                          }}
                          formatter={(
                            _value: unknown,
                            _name: unknown,
                            entry: {
                              payload?: {
                                delta: number
                                bMean: number | null
                                aMean: number | null
                                bN: number
                                aN: number
                              }
                            },
                          ) => {
                            const p = entry?.payload
                            if (!p) return ['', '']
                            const bStr =
                              p.bMean != null ? p.bMean.toFixed(2) : '—'
                            const aStr =
                              p.aMean != null ? p.aMean.toFixed(2) : '—'
                            return [
                              `${t('condition.post_match.delta')}=${p.delta.toFixed(2)} (${t('condition.post_match.before')}=${bStr} N=${p.bN}, ${t('condition.post_match.after')}=${aStr} N=${p.aN})`,
                              '',
                            ]
                          }}
                        />
                        <Bar dataKey="delta">
                          {chartData.map((d, i) => (
                            <Cell
                              key={i}
                              fill={d.delta >= 0 ? posColor : negColor}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </RoleGuard>
  )
}

export default ConditionPostMatchChange
