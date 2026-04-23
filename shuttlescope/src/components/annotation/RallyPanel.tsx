import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'

interface RallyPanelProps {
  setNum: number
  rallyNum: number
  scoreA: number
  scoreB: number
  playerAName?: string
  playerBName?: string
  onConfirmRally: (winner: 'player_a' | 'player_b', endType: string) => void
  onCancelRally: () => void
  isActive: boolean
}

const END_TYPE_VALUES = ['ace', 'forced_error', 'unforced_error', 'net', 'out', 'cant_reach'] as const

export function RallyPanel({
  setNum,
  rallyNum,
  scoreA,
  scoreB,
  playerAName = 'A',
  playerBName = 'B',
  onConfirmRally,
  onCancelRally,
  isActive,
}: RallyPanelProps) {
  const { t } = useTranslation()

  return (
    <div className="flex flex-col gap-2">
      {/* スコア表示 */}
      <div className="flex items-center justify-between bg-gray-800 rounded p-2">
        <div className="text-center">
          <div className="text-xs text-gray-400">{playerAName}</div>
          <div className="text-2xl font-bold text-white">{scoreA}</div>
        </div>
        <div className="text-gray-500 text-sm">
          {t('annotator.set')} {setNum} / {t('annotator.rally')} {rallyNum}
        </div>
        <div className="text-center">
          <div className="text-xs text-gray-400">{playerBName}</div>
          <div className="text-2xl font-bold text-white">{scoreB}</div>
        </div>
      </div>

      {/* ラリー確定パネル（アクティブ時のみ表示） */}
      {isActive && (
        <div className="border border-gray-600 rounded p-2">
          <div className="text-xs text-gray-400 mb-2">{t('annotator.rally_end_select_hint')}</div>

          {/* 得点者 × 終了種別 */}
          <div className="grid grid-cols-2 gap-2 mb-2">
            {[
              { winner: 'player_a' as const, label: `${playerAName} ${t('annotator.rally_point_suffix')}` },
              { winner: 'player_b' as const, label: `${playerBName} ${t('annotator.rally_point_suffix')}` },
            ].map(({ winner, label }) => (
              <div key={winner} className="flex flex-col gap-1">
                <div className="text-xs text-gray-300 font-medium text-center">{label}</div>
                {END_TYPE_VALUES.map((value) => (
                  <button
                    key={value}
                    onClick={() => onConfirmRally(winner, value)}
                    className="px-2 py-1 bg-gray-700 hover:bg-blue-700 text-gray-200 rounded text-xs transition-colors"
                  >
                    {t(`end_types.${value}`)}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* アクション */}
      <div className="flex gap-2">
        <button
          onClick={onCancelRally}
          className="flex-1 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
        >
          ← {t('annotator.rally_cancel')}
        </button>
      </div>
    </div>
  )
}
