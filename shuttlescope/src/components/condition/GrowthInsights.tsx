import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { ChevronDown, ChevronUp, Info } from 'lucide-react'
import { useInsights } from '@/hooks/useConditionAnalytics'
import type { GrowthCard } from '@/hooks/useConditionAnalytics'
import { useAuth } from '@/hooks/useAuth'

interface Props {
  playerId: number
  isLight: boolean
}

// ── 体調分析用信頼度（週数ベース、球数ベースの ConfidenceBadge は使わない） ──
function ConditionConfidenceBadge({ n }: { n: number }) {
  const { t } = useTranslation()
  let stars: string
  let key: string
  let colorClass: string

  if (n < 10) {
    stars = '★☆☆'
    key = 'condition.insights.growth_card.confidence_low'
    colorClass = 'border-red-400 bg-red-900/20 text-red-300'
  } else if (n < 30) {
    stars = '★★☆'
    key = 'condition.insights.growth_card.confidence_medium'
    colorClass = 'border-yellow-400 bg-yellow-900/20 text-yellow-300'
  } else {
    stars = '★★★'
    key = 'condition.insights.growth_card.confidence_high'
    colorClass = 'border-green-400 bg-green-900/20 text-green-300'
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-mono ${colorClass}`}
      title={t('condition.insights.growth_card.confidence_basis')}
    >
      {stars} <span className="font-sans">{t(key)}</span>
    </span>
  )
}

// ── 個別インサイトカード ────────────────────────────────────────────────────
function GrowthCardItem({ c, isLight, borderColor }: {
  c: GrowthCard
  isLight: boolean
  borderColor: string
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  const cardBg      = isLight ? 'bg-gray-50'     : 'bg-gray-900'
  const labelMuted  = isLight ? 'text-gray-500'   : 'text-gray-400'
  const labelStrong = isLight ? 'text-gray-800'   : 'text-gray-100'
  const sepColor    = isLight ? 'border-gray-200' : 'border-gray-700'

  // 指標名（factor_key → i18n）
  const factorLabel = c.factor_key
    ? t(`condition.insights.growth_card.factor.${c.factor_key}`, {
        defaultValue: t('condition.insights.growth_card.factor.default', { key: c.factor_key }),
      })
    : t(`condition.insights.growth_card.when.${c.when_key}`, {
        defaultValue: t('condition.insights.growth_card.when.default', { key: c.when_key }),
      })

  // 条件文（「〜が高い週」）
  const whenLabel = t(`condition.insights.growth_card.when.${c.when_key}`, {
    defaultValue: t('condition.insights.growth_card.when.default', { key: c.when_key }),
  })

  const winHigh  = c.win_rate_high  != null ? `${Math.round(c.win_rate_high  * 100)}%` : '—'
  const winOther = c.win_rate_other != null ? `${Math.round(c.win_rate_other * 100)}%` : '—'
  const nHigh    = c.n_high  ?? 0
  const nOther   = c.n_other ?? 0
  const nTotal   = c.sample_n ?? (nHigh + nOther)

  return (
    <div className={`rounded-lg border ${borderColor} ${cardBg} flex flex-col gap-0 overflow-hidden`}>
      {/* ── ヘッダー: 指標名 ── */}
      <div className={`px-3 pt-3 pb-1 text-xs font-semibold ${labelStrong}`}>
        {factorLabel}
      </div>

      {/* ── メインメッセージ ── */}
      <div className="px-3 pb-2 flex flex-col gap-1.5">
        <p className={`text-xs ${labelMuted}`}>{whenLabel}は</p>

        {/* 勝率変化 */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs ${labelMuted}`}>
            {t('condition.insights.growth_card.win_rate_other')}: <strong>{winOther}</strong>
          </span>
          <span className="text-gray-400 text-xs">→</span>
          <span className={`text-xs ${labelMuted}`}>
            {t('condition.insights.growth_card.win_rate_high')}: <strong className="text-emerald-500">{winHigh}</strong>
          </span>
          {c.effect && (
            <span className="text-sm font-bold text-emerald-500">{c.effect} 勝率↑</span>
          )}
        </div>
      </div>

      {/* ── 信頼性 + 詳細トグル ── */}
      <div className={`px-3 py-2 border-t ${sepColor} flex items-center justify-between gap-2`}>
        <ConditionConfidenceBadge n={nTotal} />
        <button
          onClick={() => setExpanded(v => !v)}
          className={`flex items-center gap-0.5 text-[11px] ${labelMuted} hover:text-blue-400`}
        >
          {t('condition.insights.growth_card.basis_label')}
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      </div>

      {/* ── 展開: 根拠の詳細 ── */}
      {expanded && (
        <div className={`px-3 pb-3 pt-1 border-t ${sepColor} space-y-2`}>
          {/* サンプル内訳 */}
          <div className={`text-xs ${labelMuted} flex flex-wrap gap-3`}>
            <span>
              {t('condition.insights.growth_card.n_high_weeks', { n: nHigh })}
              <span className="ml-1 text-emerald-500">(勝率 {winHigh})</span>
            </span>
            <span>
              {t('condition.insights.growth_card.n_other_weeks', { n: nOther })}
              <span className="ml-1">(勝率 {winOther})</span>
            </span>
          </div>

          {/* 合計N + 信頼度基準 */}
          <div className={`text-xs ${labelMuted}`}>
            {t('condition.insights.growth_card.basis_total', { n: nTotal })}
            <span className={`ml-2 font-mono text-[10px] ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
              （{t('condition.insights.growth_card.confidence_basis')}）
            </span>
          </div>

          {/* 注釈: 相関であり因果ではない */}
          <div className={`text-[10px] ${isLight ? 'text-gray-400' : 'text-gray-600'} flex items-start gap-1`}>
            <Info size={10} className="shrink-0 mt-0.5" />
            <span>{t('condition.insights.growth_card.mechanism')}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── メインコンポーネント ───────────────────────────────────────────────────
export function GrowthInsights({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { data, isLoading, error } = useInsights(playerId)

  const panelBg     = isLight ? 'bg-white'      : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted   = isLight ? 'text-gray-500'   : 'text-gray-400'
  const isPlayer    = role === 'player'

  const allCards = data?.growth_cards ?? []
  // ★★☆以上（N≥10）のみ表示
  const cards = allCards.filter(c => (c.sample_n ?? 0) >= 10)
  const hiddenCount = allCards.length - cards.length
  const trend = data?.personal_trend

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <h2 className="text-sm font-semibold mb-3">
        {isPlayer
          ? t('condition.insights.title_player')
          : t('condition.insights.title_coach')}
      </h2>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.insights.loading')}</div>
      ) : error ? (
        <div className={`${textMuted} text-xs`}>{t('condition.insights.no_data')}</div>
      ) : (
        <div className="space-y-4">
          {/* ── growth cards ── */}
          {cards.length > 0 ? (
            <>
              <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">
                {cards.map((c, idx) => (
                  <GrowthCardItem
                    key={idx}
                    c={c}
                    isLight={isLight}
                    borderColor={borderColor}
                  />
                ))}
              </div>
              {hiddenCount > 0 && (
                <div className={`text-[11px] ${textMuted}`}>
                  {t('condition.insights.growth_card.low_confidence_hidden')}
                  （{hiddenCount}件）
                </div>
              )}
            </>
          ) : allCards.length > 0 ? (
            <div className={`${textMuted} text-xs`}>
              {t('condition.insights.growth_card.low_confidence_hidden')}
            </div>
          ) : (
            <div className={`${textMuted} text-xs`}>
              {t('condition.insights.accumulating')}
            </div>
          )}

          {/* ── CCS 28日移動平均 ── */}
          {trend && trend.ccs_28ma != null && (
            <div className={`flex items-center gap-3 text-xs ${textMuted}`}>
              <span>{t('condition.insights.ccs_28ma')}:</span>
              <span className="font-mono">{trend.ccs_28ma.toFixed(1)}</span>
              {trend.direction && (
                <span>{t(`condition.insights.direction.${trend.direction}`)}</span>
              )}
            </div>
          )}

          {/* ── coach/analyst 向け: raw factor trend + validity ── */}
          {!isPlayer && data?.raw_factor_trends && data.raw_factor_trends.length > 0 && (
            <div className={`pt-3 border-t ${borderColor} space-y-3`}>
              <div className={`text-xs ${textMuted}`}>
                {t('condition.insights.raw_factor_trends')}
              </div>
              {data.raw_factor_trends.map((ft) => (
                <div key={ft.factor}>
                  <div className="text-xs mb-1 font-medium">
                    {t(`condition.factor.${ft.factor}`, { defaultValue: ft.factor })}
                  </div>
                  <div style={{ width: '100%', height: 100 }}>
                    <ResponsiveContainer>
                      <LineChart data={ft.series} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          stroke={isLight ? '#e5e7eb' : '#374151'}
                        />
                        <XAxis
                          dataKey="date"
                          tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 10 }}
                        />
                        <YAxis tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: isLight ? '#ffffff' : '#1f2937',
                            border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
                            fontSize: 11,
                          }}
                        />
                        <Line type="monotone" dataKey="value" stroke="#3b82f6" dot={false} strokeWidth={2} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isPlayer && data?.validity_summary && (
            <div className={`pt-3 border-t ${borderColor} text-xs ${textMuted}`}>
              <span className="mr-2">{t('condition.insights.validity_summary')}:</span>
              {data.validity_summary.valid_ratio != null && (
                <span className="font-mono">
                  {(data.validity_summary.valid_ratio * 100).toFixed(0)}%
                </span>
              )}
              {data.validity_summary.flags && data.validity_summary.flags.length > 0 && (
                <span className="ml-2">
                  ({data.validity_summary.flags.join(', ')})
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
