import { useTranslation } from 'react-i18next'
import { useBestProfile } from '@/hooks/useConditionAnalytics'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { useAuth } from '@/hooks/useAuth'

// 「ベスト身体・メンタルプロフィール」カード
// coach/analyst: 勝率 in_profile vs outside + key_factors レンジ
// player: 肯定的に「良い試合をする時の特徴」
interface Props {
  playerId: number
  isLight: boolean
}

const FACTOR_UNITS: Record<string, string> = {
  muscle_mass_kg: 'kg',
  weight_kg: 'kg',
  body_fat_pct: '%',
  ccs: '',
  hooper_index: '',
  sleep_hours: 'h',
  session_rpe: '',
}

function formatRange(min: number | null | undefined, max: number | null | undefined, unit: string): string {
  if (min == null && max == null) return '—'
  const lo = min != null ? min.toFixed(1) : '—'
  const hi = max != null ? max.toFixed(1) : '—'
  return `${lo} 〜 ${hi} ${unit}`.trim()
}

export function BestProfileCard({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { data, isLoading, error } = useBestProfile(playerId)

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const isPlayer = role === 'player'

  const topFactors = (data?.key_factors ?? []).slice(0, 3)
  const n = data?.n_matches ?? 0
  const inRate = data?.win_rate_in_profile
  const outRate = data?.win_rate_outside

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold">
          {isPlayer
            ? t('condition.best_profile.title_player')
            : t('condition.best_profile.title_coach')}
        </h2>
        {n > 0 && <ConfidenceBadge sampleSize={n} />}
      </div>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.best_profile.loading')}</div>
      ) : error || !data ? (
        <div className={`${textMuted} text-xs`}>{t('condition.best_profile.no_data')}</div>
      ) : (
        <div className="space-y-4">
          {/* key factors レンジ */}
          {topFactors.length > 0 && (
            <div>
              <div className={`text-xs ${textMuted} mb-2`}>
                {isPlayer
                  ? t('condition.best_profile.player_intro')
                  : t('condition.best_profile.factors_label')}
              </div>
              <ul className="space-y-1.5">
                {topFactors.map((f) => {
                  const unit = FACTOR_UNITS[f.key] ?? ''
                  const label = t(`condition.best_profile.key.${f.key}`, { defaultValue: f.key })
                  return (
                    <li key={f.key} className="text-sm flex items-center gap-2">
                      <span className="inline-block w-2 h-2 rounded-full bg-pink-500" />
                      <span>{label}</span>
                      <span className="font-mono text-xs">
                        {formatRange(f.min, f.max, unit)}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {/* 勝率比較（coach/analyst のみ直接数値） */}
          {!isPlayer && inRate != null && outRate != null && (
            <div className={`pt-3 border-t ${borderColor}`}>
              <div className={`text-xs ${textMuted} mb-2`}>
                {t('condition.best_profile.win_rate_compare')}
              </div>
              <div className="flex gap-4 text-sm">
                <div>
                  <span className={textMuted}>{t('condition.best_profile.in_profile')}: </span>
                  <span className="font-mono text-green-500">
                    {(inRate * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className={textMuted}>{t('condition.best_profile.outside')}: </span>
                  <span className="font-mono">{(outRate * 100).toFixed(1)}%</span>
                </div>
              </div>
            </div>
          )}

          {isPlayer && (
            <div className={`text-xs ${textMuted} italic pt-2`}>
              {t('condition.best_profile.player_note')}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
