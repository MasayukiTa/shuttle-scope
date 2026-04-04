import { useTranslation } from 'react-i18next'
import { StrokeInput } from '@/types'

interface StrokeHistoryProps {
  strokes: StrokeInput[]
  playerAName?: string
  playerBName?: string
}

/**
 * 直近ストローク履歴表示
 * 「①A:クリア→BC」形式で表示
 */
export function StrokeHistory({ strokes, playerAName = 'A', playerBName = 'B' }: StrokeHistoryProps) {
  const { t } = useTranslation()

  // 直近5球のみ表示
  const recent = strokes.slice(-5)

  if (recent.length === 0) {
    return (
      <div className="text-xs text-gray-500 italic text-center py-2">
        ストローク未記録
      </div>
    )
  }

  const circledNumbers = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']

  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-gray-500">{t('annotator.recent_strokes')}</div>
      {recent.map((stroke, idx) => {
        const playerLabel = stroke.player === 'player_a' ? playerAName : playerBName
        const shotLabel = t(`shot_types.${stroke.shot_type}`)
        const landLabel = stroke.land_zone ? `→${stroke.land_zone}` : ''
        const hitLabel = stroke.hit_zone ? `(${stroke.hit_zone})` : ''
        const num = circledNumbers[(stroke.stroke_num - 1) % 10]
        const isLatest = idx === recent.length - 1

        return (
          <div
            key={stroke.stroke_num}
            className={`text-xs px-2 py-0.5 rounded font-mono ${isLatest ? 'bg-blue-900/40 text-blue-200' : 'text-gray-400'}`}
          >
            {num}{playerLabel}:{shotLabel}{hitLabel}{landLabel}
          </div>
        )
      })}
    </div>
  )
}
