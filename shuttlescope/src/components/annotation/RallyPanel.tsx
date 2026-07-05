import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

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
    <div className="flex flex-col gap-2" data-tutorial="annotator.rallyPanel">
      {/* スコア表示 */}
      <div className="flex items-center justify-between bg-[var(--ss-surface-2)] rounded-ss-md p-2">
        <div className="text-center">
          <div className="text-xs text-[var(--ss-t3)]">{playerAName}</div>
          <div className="text-2xl font-bold ss-num text-[var(--ss-t1)]">{scoreA}</div>
        </div>
        <div className="text-[var(--ss-t3)] text-sm ss-num">
          {t('annotator.set')} {setNum} / {t('annotator.rally')} {rallyNum}
        </div>
        <div className="text-center">
          <div className="text-xs text-[var(--ss-t3)]">{playerBName}</div>
          <div className="text-2xl font-bold ss-num text-[var(--ss-t1)]">{scoreB}</div>
        </div>
      </div>

      {/* ラリー確定パネル（アクティブ時のみ表示） */}
      {isActive && (
        <div className="border border-[var(--ss-border-strong)] rounded-ss-md p-2">
          <div className="text-xs text-[var(--ss-t3)] mb-2">{t('annotator.rally_end_select_hint')}</div>

          {/* 得点者 × 終了種別 */}
          <div className="grid grid-cols-2 gap-2 mb-2">
            {[
              { winner: 'player_a' as const, label: `${playerAName} ${t('annotator.rally_point_suffix')}` },
              { winner: 'player_b' as const, label: `${playerBName} ${t('annotator.rally_point_suffix')}` },
            ].map(({ winner, label }) => (
              <div key={winner} className="flex flex-col gap-1">
                <div className="text-xs text-[var(--ss-t2)] font-medium text-center">{label}</div>
                {END_TYPE_VALUES.map((value) => (
                  <button
                    key={value}
                    onClick={() => onConfirmRally(winner, value)}
                    className="px-2 py-1 bg-[var(--ss-surface-2)] hover:bg-[var(--ss-brand)] text-[var(--ss-t2)] hover:text-white rounded-ss-md text-xs transition-colors duration-fast ease-out"
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
          className="flex-1 py-1.5 bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] hover:bg-[var(--ss-surface-3)] text-[var(--ss-t2)] rounded-ss-md text-sm inline-flex items-center justify-center gap-1 transition-colors duration-fast ease-out"
        >
          <MIcon name="arrow_back" size={14} /> {t('annotator.rally_cancel')}
        </button>
      </div>
    </div>
  )
}
