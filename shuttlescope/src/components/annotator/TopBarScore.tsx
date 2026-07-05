/**
 * U1: 上バー中央のスコア表示。試合中遠目から確認できる大型表示。
 */
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'

interface TopBarScoreProps {
  scoreA: number
  scoreB: number
  setNum?: number
  isMobile?: boolean
}

export function TopBarScore({ scoreA, scoreB, setNum, isMobile }: TopBarScoreProps) {
  const { t } = useTranslation()
  return (
    <div
      className={clsx(
        'flex items-baseline gap-1 font-mono font-bold tabular-nums ss-num select-none',
        isMobile ? 'text-base' : 'text-2xl',
      )}
      aria-label={setNum
        ? t('annotator.ux.score_aria_game', { a: scoreA, b: scoreB, n: setNum })
        : t('annotator.ux.score_aria', { a: scoreA, b: scoreB })}
    >
      <span className={scoreA >= scoreB ? 'text-[var(--ss-t1)]' : 'text-[var(--ss-t3)]'}>{scoreA}</span>
      <span className="text-[var(--ss-t3)]">-</span>
      <span className={scoreB >= scoreA ? 'text-[var(--ss-t1)]' : 'text-[var(--ss-t3)]'}>{scoreB}</span>
      {setNum != null && (
        <span className={clsx('ml-2 text-[var(--ss-t3)] font-normal', isMobile ? 'text-[10px]' : 'text-xs')}>
          G{setNum}
        </span>
      )}
    </div>
  )
}
