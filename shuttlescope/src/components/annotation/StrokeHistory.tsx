import { useTranslation } from 'react-i18next'
import { StrokeInput } from '@/types'

interface StrokeHistoryProps {
  strokes: StrokeInput[]
  playerAName?: string
  playerBName?: string
  partnerAName?: string
  partnerBName?: string
  playerATeam?: string
  playerBTeam?: string
  /** T4: land_zone なしを soft warning 表示するか */
  showLandZoneWarning?: boolean
}

/**
 * 直近ストローク履歴表示
 * 「①A:クリア→BC」形式で表示
 */
export function StrokeHistory({ strokes, playerAName = 'A', playerBName = 'B', partnerAName, partnerBName, playerATeam, playerBTeam, showLandZoneWarning = false }: StrokeHistoryProps) {
  const { t } = useTranslation()

  // 直近5球のみ表示
  const recent = strokes.slice(-5)

  if (recent.length === 0) {
    return (
      <div className="text-xs text-gray-500 italic text-center py-2">
        {t('annotator.stroke_none')}
      </div>
    )
  }

  const circledNumbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

  function resolvePlayerLabel(player: string): string {
    if (player === 'player_a') return playerAName
    if (player === 'player_b') return playerBName
    if (player === 'partner_a') return partnerAName ?? `${playerAName}P`
    if (player === 'partner_b') return partnerBName ?? `${playerBName}P`
    return player
  }

  function resolveTeamTooltip(player: string): string | undefined {
    if (player === 'player_a' || player === 'partner_a') return playerATeam ? `${t('annotator.team_tooltip_prefix')} ${playerATeam}` : undefined
    if (player === 'player_b' || player === 'partner_b') return playerBTeam ? `${t('annotator.team_tooltip_prefix')} ${playerBTeam}` : undefined
    return undefined
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-gray-500">{t('annotator.recent_strokes')}</div>
      {recent.map((stroke, idx) => {
        const playerLabel = resolvePlayerLabel(stroke.player)
        const teamTooltip = resolveTeamTooltip(stroke.player)
        const shotLabel = t(`shot_types.${stroke.shot_type}`)
        const landLabel = stroke.land_zone ? `→${stroke.land_zone}` : ''
        const missingLand = showLandZoneWarning && !stroke.land_zone
        const hitLabel = stroke.hit_zone ? `(${stroke.hit_zone})` : ''
        const num = circledNumbers[(stroke.stroke_num - 1) % 10]
        const isLatest = idx === recent.length - 1

        return (
          <div
            key={stroke.stroke_num}
            className={`text-xs px-2 py-0.5 rounded font-mono flex items-center gap-1.5 ${isLatest ? 'bg-gray-700 text-gray-100' : 'text-gray-400'}`}
          >
            <span title={teamTooltip}>{num}{playerLabel}:{shotLabel}{hitLabel}{landLabel}</span>
            {missingLand && (
              <span className="text-[9px] text-yellow-700/80 border border-yellow-700/30 rounded px-1 shrink-0">{t('annotator.missing_land_zone')}</span>
            )}
          </div>
        )
      })}
    </div>
  )
}
