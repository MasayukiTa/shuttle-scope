import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useBestProfile } from '@/hooks/useConditionAnalytics'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  playerId: number
  isLight: boolean
}

const FACTOR_UNITS: Record<string, string> = {
  muscle_mass_kg: 'kg',
  weight_kg: 'kg',
  body_fat_pct: '%',
  ccs_score: '',
  ccs: '',
  f1_physical: '',
  f2_stress: '',
  f3_mood: '',
  f4_motivation: '',
  f5_sleep_life: '',
  hooper_index: '',
  sleep_hours: 'h',
  session_rpe: '',
  session_load: '',
  ecw_ratio: '',
}

// 試合数ベースの信頼度バッジ
function MatchConfidenceBadge({ n, isLight }: { n: number; isLight: boolean }) {
  const { t } = useTranslation()
  let filled: number
  let label: string
  let colorClass: string

  if (n < 5) {
    filled = 1
    label = t('condition.insights.growth_card.confidence_low')
    colorClass = 'border-[var(--ss-danger-border)] bg-[var(--ss-danger-tint)] text-[var(--ss-bad)]'
  } else if (n < 16) {
    filled = 2
    label = t('condition.insights.growth_card.confidence_medium')
    colorClass = 'border-[var(--ss-warning-border)] bg-[var(--ss-warn-tint)] text-[var(--ss-warn)]'
  } else {
    filled = 3
    label = t('condition.insights.growth_card.confidence_high')
    colorClass = 'border-[var(--ss-success-border)] bg-[var(--ss-success-tint)] text-[var(--ss-success)]'
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-ss-sm border text-xs font-mono ${colorClass}`}
      title={`サンプル数: ${n}試合`}
    >
      <span className="inline-flex">
        {Array.from({ length: 3 }, (_, i) => <MIcon key={i} name={i < filled ? 'star' : 'star_border'} size={11} />)}
      </span>
      <span className="font-sans">{label}</span>
      <span className="font-sans ml-1 opacity-70">{t('auto.BestProfileCard.n_matches_paren', { n })}</span>
    </span>
  )
}

export function BestProfileCard({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useBestProfile(playerId)

  const panelBg    = 'bg-[var(--ss-surface-1)]'
  const borderColor = 'border-[var(--ss-border)]'
  const textMuted   = 'text-[var(--ss-t2)]'
  const textStrong  = 'text-[var(--ss-t1)]'
  const sepColor    = 'border-[var(--ss-border)]'
  const topFactors = (data?.key_factors ?? []).slice(0, 5)
  const n = data?.n_matches ?? 0
  const inRate  = data?.win_rate_in_profile
  const outRate = data?.win_rate_outside
  const rateDiff = (inRate != null && outRate != null)
    ? Math.round((inRate - outRate) * 100)
    : null

  return (
    <section className={`rounded-ss-lg border shadow-card ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className={`text-sm font-semibold ${textStrong}`}>
          {t('condition.best_profile.title_coach')}
        </h2>
        {n > 0 && <MatchConfidenceBadge n={n} isLight={isLight} />}
      </div>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.best_profile.loading')}</div>
      ) : error || !data ? (
        <div className={`${textMuted} text-xs`}>{t('condition.best_profile.no_data')}</div>
      ) : (
        <div className="space-y-4">
          {/* 勝率サマリー */}
          {inRate != null && outRate != null && (
            <div className={`flex items-center gap-4 text-sm pb-3 border-b ${sepColor}`}>
              <div>
                <span className={`text-xs ${textMuted}`}>{t('condition.best_profile.in_profile')}: </span>
                <span className="font-mono ss-num font-semibold text-[var(--ss-success)]">
                  {(inRate * 100).toFixed(1)}%
                </span>
              </div>
              <span className={`text-xs ${textMuted}`}>→</span>
              <div>
                <span className={`text-xs ${textMuted}`}>{t('condition.best_profile.outside')}: </span>
                <span className="font-mono ss-num">{(outRate * 100).toFixed(1)}%</span>
              </div>
              {rateDiff != null && rateDiff > 0 && (
                <span className="text-xs font-semibold text-[var(--ss-success)] ss-num">
                  {t('auto.BestProfileCard.rate_diff_pp', { n: rateDiff })}
                </span>
              )}
            </div>
          )}

          {/* key factors + gap */}
          {topFactors.length > 0 ? (
            <div>
              <div className={`text-xs ${textMuted} mb-2`}>
                {t('condition.best_profile.factors_label')}
              </div>
              <ul className="space-y-0 divide-y divide-inherit" style={{ borderColor: 'inherit' }}>
                {topFactors.map((f) => {
                  const unit = FACTOR_UNITS[f.key] ?? ''
                  const label = t(`condition.best_profile.key.${f.key}`, { defaultValue: f.key })
                  const cur = f.current
                  const tMin = f.target_min
                  const tMax = f.target_max
                  const gap = f.gap

                  const targetRange = (tMin != null || tMax != null)
                    ? `${tMin != null ? tMin.toFixed(1) : '—'}〜${tMax != null ? tMax.toFixed(1) : '—'}${unit ? unit : ''}`
                    : null

                  let gapNode: ReactNode
                  if (gap === null || gap === undefined) {
                    gapNode = null
                  } else if (gap === 0) {
                    gapNode = (
                      <span className="font-medium text-[var(--ss-success)]">
                        <MIcon name="check" size={14} />
                      </span>
                    )
                  } else if (gap > 0) {
                    gapNode = (
                      <span className="text-[var(--ss-warn)] ss-num">
                        ↑{gap.toFixed(1)}{unit}
                      </span>
                    )
                  } else {
                    gapNode = (
                      <span className="text-[var(--ss-brand)] ss-num">
                        ↓{Math.abs(gap).toFixed(1)}{unit}
                      </span>
                    )
                  }

                  // 詳細説明: target_mean / rest_mean / direction から自動生成
                  // (それっぽい文言ではなく実数値ベース)。サンプル数下限を満たさない
                  // factor は文章を出さず数値だけ並べる。
                  const targetMean = (f as { target_mean?: number | null }).target_mean ?? null
                  const restMean = (f as { rest_mean?: number | null }).rest_mean ?? null
                  const direction = (f as { direction?: string | null }).direction ?? null
                  const showDetail = targetMean != null && restMean != null && Math.abs(targetMean - restMean) > 0.01
                  let detailText: string | null = null
                  if (showDetail) {
                    const isHigherBetter = direction === 'higher_when_winning'
                    const winSide = isHigherBetter ? '高い' : '低い'
                    const diffPp = Math.abs(targetMean - restMean).toFixed(1)
                    detailText = `勝った試合では ${targetMean.toFixed(1)}${unit}、負けた試合では ${restMean.toFixed(1)}${unit}（差 ${diffPp}${unit}、勝つときの方が${winSide}）。`
                  }

                  return (
                    <li key={f.key} className={`py-1.5 ${sepColor}`}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-xs font-medium ${textStrong} shrink-0`}>{label}</span>
                        {cur != null && (
                          <span className={`text-xs font-mono ss-num ${textMuted} shrink-0`}>
                            {t('auto.BestProfileCard.current_label')} <strong>{cur.toFixed(1)}{unit}</strong>
                          </span>
                        )}
                        {targetRange && (
                          <span className={`text-[11px] font-mono ss-num ${textMuted} shrink-0`}>
                            {t('auto.BestProfileCard.target_range', { r: targetRange })}
                          </span>
                        )}
                        {gapNode && <span className="text-xs shrink-0">{gapNode}</span>}
                      </div>
                      {detailText && (
                        <div className={`text-[11px] mt-0.5 leading-snug ${textMuted}`}>
                          {detailText}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : (
            <div className={`${textMuted} text-xs`}>{t('condition.best_profile.no_data')}</div>
          )}

          {/* 期待勝率改善 */}
          {rateDiff != null && rateDiff > 0 && (
            <div className={`pt-2 border-t ${sepColor} flex items-start gap-1.5 text-xs ${textMuted}`}>
              <MIcon name="info" size={11} className="shrink-0 mt-0.5" />
              <span>
                {t('condition.best_profile.win_rate_improvement', { diff: rateDiff })}
              </span>
            </div>
          )}

        </div>
      )}
    </section>
  )
}
