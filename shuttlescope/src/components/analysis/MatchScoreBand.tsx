// セット別スコアバンド表示コンポーネント
import { useTranslation } from 'react-i18next'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface BandEntry {
  my_low: number
  my_high: number
  opp_low: number
  opp_high: number
  sample: number
}

interface MatchScoreBandProps {
  scoreBands: Record<string, BandEntry>
  playerName: string
  opponentName: string
}

export function MatchScoreBand({ scoreBands, playerName, opponentName }: MatchScoreBandProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const textColor = isLight ? '#334155' : '#d1d5db'
  const subColor = isLight ? '#64748b' : '#9ca3af'

  const entries = (['set1', 'set2', 'set3'] as const)
    .map((k) => ({ key: k, band: scoreBands[k] }))
    .filter((e) => e.band != null)

  if (entries.length === 0) {
    return (
      <p className="text-xs text-gray-500 text-center py-2">
        スコアデータが不足しています
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-2 text-[10px] font-medium pb-1 border-b border-gray-700">
        <span style={{ color: subColor }}>セット</span>
        <span className="text-center" style={{ color: subColor }}>{t('prediction.my_score')}</span>
        <span className="text-center" style={{ color: subColor }}>{t('prediction.opp_score')}</span>
        <span className="text-right" style={{ color: subColor }}>N</span>
      </div>
      {entries.map(({ key, band }) => {
        const setNum = key.replace('set', '')
        return (
          <div key={key} className="grid grid-cols-4 gap-2 text-xs items-center">
            <span className="font-medium" style={{ color: textColor }}>Set {setNum}</span>
            <span className="text-center font-mono" style={{ color: textColor }}>
              {band.my_low}–{band.my_high}
            </span>
            <span className="text-center font-mono" style={{ color: subColor }}>
              {band.opp_low}–{band.opp_high}
            </span>
            <span className="text-right text-[10px]" style={{ color: subColor }}>
              {band.sample}
            </span>
          </div>
        )
      })}
      <p className="text-[10px] text-gray-600 pt-1">
        25–75 パーセンタイル帯
      </p>
    </div>
  )
}
