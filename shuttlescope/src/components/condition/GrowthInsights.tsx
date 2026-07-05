import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { MIcon } from '@/components/common/MIcon'
import { useInsights } from '@/hooks/useConditionAnalytics'
import type { GrowthCard } from '@/hooks/useConditionAnalytics'
import { useAuth } from '@/hooks/useAuth'
import { catColor } from '@/styles/categoricalPalette'

interface Props {
  playerId: number
  isLight: boolean
}

// ── 体調分析用信頼度バッジ（週数ベース）──────────────────────────────────
function ConditionConfidenceBadge({ n, isLight }: { n: number; isLight: boolean }) {
  const { t } = useTranslation()
  let filled: number
  let key: string
  let colorClass: string

  if (n < 10) {
    filled = 1
    key = 'condition.insights.growth_card.confidence_low'
    colorClass = 'border-[var(--ss-danger-border)] bg-[var(--ss-danger-tint)] text-[var(--ss-bad)]'
  } else if (n < 30) {
    filled = 2
    key = 'condition.insights.growth_card.confidence_medium'
    colorClass = 'border-[var(--ss-warning-border)] bg-[var(--ss-warn-tint)] text-[var(--ss-warn)]'
  } else {
    filled = 3
    key = 'condition.insights.growth_card.confidence_high'
    colorClass = 'border-[var(--ss-success-border)] bg-[var(--ss-success-tint)] text-[var(--ss-success)]'
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-ss-sm border text-xs font-mono ${colorClass}`}
      title={t('condition.insights.growth_card.confidence_basis')}
    >
      <span className="inline-flex">
        {Array.from({ length: 3 }, (_, i) => <MIcon key={i} name={i < filled ? 'star' : 'star_border'} size={11} />)}
      </span>
      <span className="font-sans">{t(key)}</span>
    </span>
  )
}

// ── 一行リスト表示のインサイト行 ──────────────────────────────────────────
function GrowthCardRow({ c, isLight, sepColor }: {
  c: GrowthCard
  isLight: boolean
  sepColor: string
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  const labelMuted  = 'text-[var(--ss-t2)]'
  const labelStrong = 'text-[var(--ss-t1)]'
  const expandBg    = 'bg-[var(--ss-surface-2)]'

  const factorLabel = c.factor_key
    ? t(`condition.insights.growth_card.factor.${c.factor_key}`, {
        defaultValue: t('condition.insights.growth_card.factor.default', { key: c.factor_key }),
      })
    : t(`condition.insights.growth_card.when.${c.when_key}`, {
        defaultValue: t('condition.insights.growth_card.when.default', { key: c.when_key }),
      })

  const whenLabel = t(`condition.insights.growth_card.when.${c.when_key}`, {
    defaultValue: t('condition.insights.growth_card.when.default', { key: c.when_key }),
  })

  const winHigh  = c.win_rate_high  != null ? `${Math.round(c.win_rate_high  * 100)}%` : '—'
  const winOther = c.win_rate_other != null ? `${Math.round(c.win_rate_other * 100)}%` : '—'
  const nHigh    = c.n_high  ?? 0
  const nOther   = c.n_other ?? 0
  const nTotal   = c.sample_n ?? (nHigh + nOther)

  return (
    <div className={`border-b last:border-0 ${sepColor}`}>
      {/* ── メイン行 ── */}
      <div className="flex items-center gap-4 py-3 px-1 flex-wrap">
        {/* 左: 指標名 + 勝率変化 */}
        <div className="flex-1 min-w-0 flex items-center gap-3 flex-wrap">
          <span className={`text-sm font-medium ${labelStrong} whitespace-nowrap`}>
            {factorLabel}
          </span>
          <span className={`text-xs ${labelMuted} whitespace-nowrap`}>
            {whenLabel}
          </span>
          <div className="flex items-center gap-1.5 text-sm whitespace-nowrap">
            <span className={`font-mono ss-num ${labelMuted}`}>{winOther}</span>
            <span className={labelMuted}>→</span>
            <span className="font-mono ss-num font-semibold text-[var(--ss-success)]">{winHigh}</span>
            {c.effect && (
              <span className="font-bold text-[var(--ss-success)] ml-0.5">{t('auto.GrowthInsights.k_effect_winrate_up', { effect: c.effect })}</span>
            )}
          </div>
        </div>

        {/* 右: 信頼度 + 詳細ボタン */}
        <div className="flex items-center gap-2 shrink-0">
          <ConditionConfidenceBadge n={nTotal} isLight={isLight} />
          <button
            onClick={() => setExpanded(v => !v)}
            className={`flex items-center gap-0.5 text-[11px] ${labelMuted} hover:text-[var(--ss-brand)] whitespace-nowrap duration-base ease-out`}
          >
            {t('condition.insights.growth_card.basis_label')}
            {expanded ? <MIcon name="expand_less" size={12} /> : <MIcon name="expand_more" size={12} />}
          </button>
        </div>
      </div>

      {/* ── 展開: 根拠の詳細 ── */}
      {expanded && (
        <div className={`px-4 pb-3 pt-1 ${expandBg} rounded-b-ss-sm space-y-1.5`}>
          <div className={`text-xs ${labelMuted} flex flex-wrap gap-4`}>
            <span>
              {t('condition.insights.growth_card.n_high_weeks', { n: nHigh })}
              <span className="ml-1 text-[var(--ss-success)] ss-num">{t('auto.GrowthInsights.k_winrate_paren', { rate: winHigh })}</span>
            </span>
            <span>
              {t('condition.insights.growth_card.n_other_weeks', { n: nOther })}
              <span className="ml-1 ss-num">{t('auto.GrowthInsights.k_winrate_paren', { rate: winOther })}</span>
            </span>
            <span className="font-mono text-[10px] text-[var(--ss-t3)]">
              {t('condition.insights.growth_card.basis_total', { n: nTotal })}
            </span>
          </div>
          <div className="text-[10px] text-[var(--ss-t3)] flex items-start gap-1">
            <MIcon name="info" size={10} className="shrink-0 mt-0.5" />
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

  const panelBg     = 'bg-[var(--ss-surface-1)]'
  const borderColor = 'border-[var(--ss-border)]'
  const sepColor    = 'border-[var(--ss-border)]'
  const textMuted   = 'text-[var(--ss-t2)]'
  const isPlayer    = role === 'player'

  const allCards = data?.growth_cards ?? []
  // ★★☆以上（N≥10）のみ表示
  const cards = allCards.filter(c => (c.sample_n ?? 0) >= 10)
  const hiddenCount = allCards.length - cards.length
  const trend = data?.personal_trend

  return (
    <section className={`rounded-ss-lg border shadow-card ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-[var(--ss-t1)]">
          {isPlayer
            ? t('condition.insights.title_player')
            : t('condition.insights.title_coach')}
        </h2>
        {trend && trend.ccs_28ma != null && (
          <div className={`flex items-center gap-2 text-xs ${textMuted}`}>
            <span>{t('condition.insights.ccs_28ma')}:</span>
            <span className="font-mono ss-num">{trend.ccs_28ma.toFixed(1)}</span>
            {trend.direction && (
              <span>{t(`condition.insights.direction.${trend.direction}`)}</span>
            )}
          </div>
        )}
      </div>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.insights.loading')}</div>
      ) : error ? (
        <div className={`${textMuted} text-xs`}>{t('condition.insights.no_data')}</div>
      ) : (
        <div>
          {/* ── growth cards（リスト形式） ── */}
          {cards.length > 0 ? (
            <>
              <div>
                {cards.map((c, idx) => (
                  <GrowthCardRow
                    key={idx}
                    c={c}
                    isLight={isLight}
                    sepColor={sepColor}
                  />
                ))}
              </div>
              {hiddenCount > 0 && (
                <div className={`mt-2 text-[11px] ${textMuted}`}>
                  {t('auto.GrowthInsights.k_low_conf_hidden_count', { label: t('condition.insights.growth_card.low_confidence_hidden'), n: hiddenCount })}
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

          {/* ── coach/analyst 向け: raw factor trend + validity ── */}
          {!isPlayer && data?.raw_factor_trends && data.raw_factor_trends.length > 0 && (
            <div className={`mt-4 pt-3 border-t ${borderColor} space-y-3`}>
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
                          stroke="var(--ss-border)"
                        />
                        <XAxis
                          dataKey="date"
                          tick={{ fill: 'var(--ss-t2)', fontSize: 10 }}
                        />
                        <YAxis tick={{ fill: 'var(--ss-t2)', fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: 'var(--ss-surface-1)',
                            border: '1px solid var(--ss-border)',
                            fontSize: 11,
                          }}
                        />
                        <Line type="monotone" dataKey="value" stroke={catColor('Cool', isLight)} dot={false} strokeWidth={2} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!isPlayer && data?.validity_summary && (
            <div className={`mt-3 pt-3 border-t ${borderColor} text-xs ${textMuted}`}>
              <span className="mr-2">{t('condition.insights.validity_summary')}:</span>
              {data.validity_summary.valid_ratio != null && (
                <span className="font-mono ss-num">
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
