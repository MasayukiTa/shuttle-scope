import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { useBestProfile } from '@/hooks/useConditionAnalytics'

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
  let stars: string
  let label: string
  let colorClass: string

  if (n < 5) {
    stars = '★☆☆'
    label = t('condition.insights.growth_card.confidence_low')
    colorClass = isLight
      ? 'border-red-300 bg-red-50 text-red-600'
      : 'border-red-400 bg-red-900/20 text-red-300'
  } else if (n < 16) {
    stars = '★★☆'
    label = t('condition.insights.growth_card.confidence_medium')
    colorClass = isLight
      ? 'border-yellow-300 bg-yellow-50 text-yellow-600'
      : 'border-yellow-400 bg-yellow-900/20 text-yellow-300'
  } else {
    stars = '★★★'
    label = t('condition.insights.growth_card.confidence_high')
    colorClass = isLight
      ? 'border-green-300 bg-green-50 text-green-600'
      : 'border-green-400 bg-green-900/20 text-green-300'
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-mono ${colorClass}`}
      title={`サンプル数: ${n}試合`}
    >
      {stars} <span className="font-sans">{label}</span>
      <span className="font-sans ml-1 opacity-70">({n}試合)</span>
    </span>
  )
}

export function BestProfileCard({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useBestProfile(playerId)

  const panelBg    = isLight ? 'bg-white'        : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted   = isLight ? 'text-gray-500'   : 'text-gray-400'
  const textStrong  = isLight ? 'text-gray-800'   : 'text-gray-100'
  const sepColor    = isLight ? 'border-gray-100' : 'border-gray-700'
  const topFactors = (data?.key_factors ?? []).slice(0, 5)
  const n = data?.n_matches ?? 0
  const inRate  = data?.win_rate_in_profile
  const outRate = data?.win_rate_outside
  const rateDiff = (inRate != null && outRate != null)
    ? Math.round((inRate - outRate) * 100)
    : null

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
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
                <span className="font-mono font-semibold text-green-500">
                  {(inRate * 100).toFixed(1)}%
                </span>
              </div>
              <span className={`text-xs ${textMuted}`}>→</span>
              <div>
                <span className={`text-xs ${textMuted}`}>{t('condition.best_profile.outside')}: </span>
                <span className="font-mono">{(outRate * 100).toFixed(1)}%</span>
              </div>
              {rateDiff != null && rateDiff > 0 && (
                <span className="text-xs font-semibold text-emerald-500">
                  +{rateDiff}pp
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

                  let gapNode: ReactNode = null
                  if (gap === null || gap === undefined) {
                    gapNode = null
                  } else if (gap === 0) {
                    gapNode = (
                      <span className={`font-medium ${isLight ? 'text-green-600' : 'text-green-400'}`}>
                        ✓
                      </span>
                    )
                  } else if (gap > 0) {
                    gapNode = (
                      <span className={`${isLight ? 'text-orange-600' : 'text-orange-400'}`}>
                        ↑{gap.toFixed(1)}{unit}
                      </span>
                    )
                  } else {
                    gapNode = (
                      <span className={`${isLight ? 'text-blue-600' : 'text-blue-400'}`}>
                        ↓{Math.abs(gap).toFixed(1)}{unit}
                      </span>
                    )
                  }

                  return (
                    <li key={f.key} className={`flex items-center gap-2 py-1.5 ${sepColor}`}>
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-pink-500 shrink-0" />
                      <span className={`text-xs font-medium ${textStrong} shrink-0`}>{label}</span>
                      {cur != null && (
                        <span className={`text-xs font-mono ${textMuted} shrink-0`}>
                          <strong>{cur.toFixed(1)}{unit}</strong>
                        </span>
                      )}
                      {targetRange && (
                        <span className={`text-[11px] font-mono ${textMuted} shrink-0`}>
                          [{targetRange}]
                        </span>
                      )}
                      {gapNode && <span className="text-xs shrink-0">{gapNode}</span>}
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
              <Info size={11} className="shrink-0 mt-0.5" />
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
