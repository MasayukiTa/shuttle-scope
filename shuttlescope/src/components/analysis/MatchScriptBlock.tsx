// MatchScriptBlock — 試合展開パターン予測 (Spec §3.2)
// fatigue_risk.breakdown + win_probability からクライアントサイドで導出。
import { useTranslation } from 'react-i18next'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { MIcon } from '@/components/common/MIcon'

interface FatigueBreakdown {
  temporal_drop: number
  long_rally_penalty: number
  pressure_drop: number
  total_rallies: number
}

interface MatchScriptBlockProps {
  winProbability: number
  fatigueBreakdown: FatigueBreakdown | null
}

interface ScriptPattern {
  // i18n キー prediction.script.<id>.label / .description の <id>
  id: string
  color: string
  iconName: string
}

function derivePattern(
  winProb: number,
  bd: FatigueBreakdown | null,
): ScriptPattern {
  const hasFatigue = bd && bd.total_rallies >= 10
  const td = bd?.temporal_drop ?? 0
  const lr = bd?.long_rally_penalty ?? 0
  const pd = bd?.pressure_drop ?? 0

  if (!hasFatigue) {
    if (winProb >= 0.60) return { id: 'favored', color: WIN, iconName: 'trending_up' }
    if (winProb <= 0.44) return { id: 'underdog', color: LOSS, iconName: 'trending_down' }
    return { id: 'even', color: '#9ca3af', iconName: 'trending_flat' }
  }

  if (winProb >= 0.60 && td < 0.08 && lr < 0.08 && pd < 0.08)
    return { id: 'stable_favored', color: WIN, iconName: 'trending_up' }

  if (winProb >= 0.55 && td >= 0.08 && lr < 0.08)
    return { id: 'early_lead', color: WIN, iconName: 'show_chart' }

  if (winProb >= 0.55 && lr >= 0.08)
    return { id: 'short_match', color: WIN, iconName: 'bolt' }

  if (winProb >= 0.45 && pd >= 0.08)
    return { id: 'deuce_risk', color: LOSS, iconName: 'warning' }

  if (winProb <= 0.44 && lr >= 0.08)
    return { id: 'long_match_risk', color: LOSS, iconName: 'trending_down' }

  if (winProb <= 0.44)
    return { id: 'comeback', color: LOSS, iconName: 'trending_down' }

  return { id: 'standard', color: '#9ca3af', iconName: 'trending_flat' }
}

export function MatchScriptBlock({ winProbability, fatigueBreakdown }: MatchScriptBlockProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const subText = isLight ? '#64748b' : '#9ca3af'

  const pattern = derivePattern(winProbability, fatigueBreakdown)
  const hasFatigue = fatigueBreakdown && fatigueBreakdown.total_rallies >= 10

  const signals: string[] = []
  if (hasFatigue && fatigueBreakdown) {
    if (fatigueBreakdown.temporal_drop >= 0.08)
      signals.push(t('prediction.script.signal_late_drop', { pct: Math.round(fatigueBreakdown.temporal_drop * 100) }))
    if (fatigueBreakdown.long_rally_penalty >= 0.08)
      signals.push(t('prediction.script.signal_long_rally_drop', { pct: Math.round(fatigueBreakdown.long_rally_penalty * 100) }))
    if (fatigueBreakdown.pressure_drop >= 0.08)
      signals.push(t('prediction.script.signal_deuce_drop', { pct: Math.round(fatigueBreakdown.pressure_drop * 100) }))
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <MIcon name={pattern.iconName} size={20} style={{ color: pattern.color }} />
        <span className="text-sm font-semibold" style={{ color: pattern.color }}>{t(`prediction.script.${pattern.id}.label`)}</span>
      </div>
      <p className="text-xs" style={{ color: subText }}>{t(`prediction.script.${pattern.id}.description`)}</p>
      {signals.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {signals.map((s, i) => (
            <span
              key={i}
              className="text-[10px] px-1.5 py-0.5 rounded-ss-sm border ss-num"
              style={{ color: LOSS, borderColor: LOSS + '66', backgroundColor: LOSS + '18' }}
            >
              {s}
            </span>
          ))}
        </div>
      )}
      {!hasFatigue && (
        <p className="text-[10px]" style={{ color: subText }}>
          {t('prediction.script_no_rally_data')}
        </p>
      )}
    </div>
  )
}
