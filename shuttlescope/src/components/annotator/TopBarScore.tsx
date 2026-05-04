/**
 * U1: 上バー中央のスコア表示。試合中遠目から確認できる大型表示。
 */
import { clsx } from 'clsx'

interface TopBarScoreProps {
  scoreA: number
  scoreB: number
  setNum?: number
  isMobile?: boolean
}

export function TopBarScore({ scoreA, scoreB, setNum, isMobile }: TopBarScoreProps) {
  return (
    <div
      className={clsx(
        'flex items-baseline gap-1 font-mono font-bold tabular-nums select-none',
        isMobile ? 'text-base' : 'text-2xl',
      )}
      aria-label={`スコア ${scoreA} 対 ${scoreB}${setNum ? ` ゲーム ${setNum}` : ''}`}
    >
      <span className={scoreA >= scoreB ? 'text-white' : 'text-gray-300'}>{scoreA}</span>
      <span className="text-gray-500">-</span>
      <span className={scoreB >= scoreA ? 'text-white' : 'text-gray-300'}>{scoreB}</span>
      {setNum != null && (
        <span className={clsx('ml-2 text-gray-400 font-normal', isMobile ? 'text-[10px]' : 'text-xs')}>
          G{setNum}
        </span>
      )}
    </div>
  )
}
