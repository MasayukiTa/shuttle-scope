/**
 * ScoreboardCompact — モバイルスティッキー / デスクトップカード共通の
 * 小型スコアボード。
 *
 * 旧コード:
 * - AnnotatorPage.tsx:3415-3447 にモバイル sticky 用 inline JSX
 * - AnnotatorPage.tsx:3453-3475 にデスクトップカード用 inline JSX
 * 両者で player A/B 名 + score + set/rally がほぼ同じ並びだったが、フォントサイズ
 * (text-4xl vs text-2xl) や min-width (80 vs 60) や中央スロット (shots vs timer) で
 * 微妙にズレていた。1 コンポーネントに集約してパターンを一本化する。
 *
 * TopBarScore (上バー大型表示) は別物 (役割が違う) のでそのまま残す。
 */
import { ReactNode } from 'react'
import { clsx } from 'clsx'
import type { Match } from '@/types'

export interface ScoreboardCompactProps {
  match: Match | undefined | null
  scoreA: number
  scoreB: number
  setNum: number
  rallyNum: number
  /** ラリー中ならストローク数 (mobile sticky 用)。0 の時は描画しない */
  strokeCount?: number
  /** 試合中モード等で大型タッチターゲット (text-4xl) を使う */
  useLargeTouch?: boolean
  /** 中央スロット (デスクトップ用タイマー等) — 渡されたら表示 */
  middleExtra?: ReactNode
  /** ラッパー className 上書き (mobile sticky だと外側で自前指定するため) */
  className?: string
}

export function ScoreboardCompact({
  match,
  scoreA,
  scoreB,
  setNum,
  rallyNum,
  strokeCount,
  useLargeTouch = false,
  middleExtra,
  className,
}: ScoreboardCompactProps) {
  const isDoubles = match?.format !== 'singles'
  const minWPlayer = useLargeTouch ? 'min-w-[80px]' : 'min-w-[60px]'
  const scoreSize = useLargeTouch ? 'text-4xl' : 'text-2xl'
  const playerLabelSize = useLargeTouch ? 'text-xs' : 'text-[10px]'
  const playerMaxW = useLargeTouch ? 'max-w-[120px]' : 'max-w-[110px]'

  const renderSide = (key: 'a' | 'b') => {
    const main = key === 'a' ? match?.player_a : match?.player_b
    const partner = key === 'a' ? match?.partner_a : match?.partner_b
    const fallback = key === 'a' ? 'A' : 'B'
    const score = key === 'a' ? scoreA : scoreB
    return (
      <div className={clsx('text-center', minWPlayer)}>
        {isDoubles ? (
          <div className={clsx('text-gray-400 leading-tight', playerLabelSize)}>
            <div className={clsx('whitespace-nowrap truncate', playerMaxW)} title={main?.name ?? fallback}>
              {main?.name ?? fallback}
            </div>
            <div className={clsx('whitespace-nowrap truncate', playerMaxW)} title={partner?.name ?? '—'}>
              {partner?.name ?? '—'}
            </div>
          </div>
        ) : (
          <div className={clsx('text-gray-400 truncate', playerLabelSize)} title={main?.name ?? fallback}>
            {main?.name ?? fallback}
          </div>
        )}
        <div className={clsx('font-bold tabular-nums', scoreSize)}>{score}</div>
      </div>
    )
  }

  return (
    <div className={clsx('flex items-center justify-between', className)}>
      {renderSide('a')}
      <div className="text-center text-xs text-gray-500 num-cell">
        <div>Set {setNum}</div>
        <div>Rally {rallyNum}</div>
        {strokeCount != null && strokeCount > 0 && (
          <div className="text-[10px] text-blue-400 mt-0.5">{strokeCount} shots</div>
        )}
        {middleExtra}
      </div>
      {renderSide('b')}
    </div>
  )
}
