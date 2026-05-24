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
  label: string
  description: string
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
    if (winProb >= 0.60) return { label: '優勢型', description: '過去実績から優勢。展開詳細は未算出。', color: WIN, iconName: 'trending_up' }
    if (winProb <= 0.44) return { label: '苦戦型', description: '過去実績では不利。戦術の精度が鍵。', color: LOSS, iconName: 'trending_down' }
    return { label: '拮抗型', description: '五分五分。試合当日の状態次第。', color: '#9ca3af', iconName: 'trending_flat' }
  }

  if (winProb >= 0.60 && td < 0.08 && lr < 0.08 && pd < 0.08)
    return { label: '安定優勢型', description: '終盤・長ラリー・デュースいずれも安定。展開を選ばない。', color: WIN, iconName: 'trending_up' }

  if (winProb >= 0.55 && td >= 0.08 && lr < 0.08)
    return { label: '序盤優勢・後半注意型', description: '序盤で差をつけたい。後半の失速に備えた体力配分を。', color: WIN, iconName: 'show_chart' }

  if (winProb >= 0.55 && lr >= 0.08)
    return { label: '短期決戦優位型', description: '長ラリーで不利。早い展開・スマッシュ多用で決着を。', color: WIN, iconName: 'bolt' }

  if (winProb >= 0.45 && pd >= 0.08)
    return { label: '接戦・デュース弱型', description: 'デュース時の集中力維持が課題。接戦での精神的準備を。', color: LOSS, iconName: 'warning' }

  if (winProb <= 0.44 && lr >= 0.08)
    return { label: '長期戦不利型', description: '長ラリーと後半で不利。逆転には早い展開での先行が必要。', color: LOSS, iconName: 'trending_down' }

  if (winProb <= 0.44)
    return { label: '逆転狙い型', description: '過去実績は不利。相手の弱点を突く戦術的工夫が必要。', color: LOSS, iconName: 'trending_down' }

  return { label: '標準型', description: '特段の傾向なし。基本戦術を軸に。', color: '#9ca3af', iconName: 'trending_flat' }
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
      signals.push(`後半失速 ${Math.round(fatigueBreakdown.temporal_drop * 100)}%`)
    if (fatigueBreakdown.long_rally_penalty >= 0.08)
      signals.push(`長ラリー後低下 ${Math.round(fatigueBreakdown.long_rally_penalty * 100)}%`)
    if (fatigueBreakdown.pressure_drop >= 0.08)
      signals.push(`デュース弱 ${Math.round(fatigueBreakdown.pressure_drop * 100)}%`)
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <MIcon name={pattern.iconName} size={20} style={{ color: pattern.color }} />
        <span className="text-sm font-semibold" style={{ color: pattern.color }}>{pattern.label}</span>
      </div>
      <p className="text-xs" style={{ color: subText }}>{pattern.description}</p>
      {signals.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {signals.map((s, i) => (
            <span
              key={i}
              className="text-[10px] px-1.5 py-0.5 rounded border"
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
