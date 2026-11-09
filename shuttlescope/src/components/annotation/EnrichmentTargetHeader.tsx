import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'
import type { StrokeInput } from '@/types'

export interface EnrichmentTargetHeaderProps {
  /** ラリー内の確定済みストローク列 */
  strokes: StrokeInput[]
  /** エンリッチメントを付ける対象ストロークの index（範囲内に丸めてから渡すこと） */
  targetIndex: number
  /** 対象を前のストロークへ切り替える */
  onPrev: () => void
  /** 対象を次のストロークへ切り替える */
  onNext: () => void
  playerAName?: string
  playerBName?: string
  partnerAName?: string
  partnerBName?: string
}

/**
 * T003 F-T003-01: エンリッチメント（詳細）パネルの見出し。
 *
 * 以前は詳細入力が常に「末尾（直前に確定した）ストローク」へ書き込まれ、しかも
 * どのストロークが対象かが画面に出ていなかった。そのためサーブへ付けたつもりの
 * 意図タグ・メモ・打点高さが、次に入力したネットショットに付いてしまっていた。
 *
 * この見出しは対象ストロークを常に明示し（何本目・ショット種別・打者）、前後ボタンで
 * 対象を切り替えられる。新しいストロークを選べば表示はそのストロークへ切り替わる。
 */
export function EnrichmentTargetHeader({
  strokes,
  targetIndex,
  onPrev,
  onNext,
  playerAName = 'A',
  playerBName = 'B',
  partnerAName,
  partnerBName,
}: EnrichmentTargetHeaderProps) {
  const { t } = useTranslation()

  const target = strokes[targetIndex]
  if (!target) return null

  const canPrev = targetIndex > 0
  const canNext = targetIndex < strokes.length - 1

  const resolveHitterLabel = (player: string): string => {
    if (player === 'player_a') return playerAName
    if (player === 'player_b') return playerBName
    if (player === 'partner_a') return partnerAName ?? `${playerAName}P`
    if (player === 'partner_b') return partnerBName ?? `${playerBName}P`
    return player
  }

  const shotLabel = t(`shot_types.${target.shot_type}`, {
    defaultValue: String(target.shot_type ?? ''),
  })
  const hitterLabel = resolveHitterLabel(target.player)

  return (
    <div
      className="flex items-center justify-between gap-2 rounded-ss-sm bg-[var(--ss-surface-3)] px-2 py-1"
      data-testid="enrichment-target"
    >
      <button
        type="button"
        disabled={!canPrev}
        onClick={onPrev}
        aria-label={t('enrichment.target_prev', { defaultValue: '前のストローク' })}
        title={t('enrichment.target_prev', { defaultValue: '前のストローク' })}
        className={clsx(
          'flex items-center px-1 py-0.5 rounded-ss-sm',
          canPrev
            ? 'text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]'
            : 'text-[var(--ss-t3)] opacity-40 cursor-not-allowed',
        )}
      >
        <MIcon name="chevron_left" size={14} />
      </button>
      <span
        className="flex-1 text-center text-[11px] text-[var(--ss-t1)]"
        data-testid="enrichment-target-label"
      >
        {t('enrichment.target_label', {
          defaultValue: '対象: {{num}}本目 {{shot}}（{{hitter}}）',
          num: target.stroke_num,
          shot: shotLabel,
          hitter: hitterLabel,
        })}
      </span>
      <button
        type="button"
        disabled={!canNext}
        onClick={onNext}
        aria-label={t('enrichment.target_next', { defaultValue: '次のストローク' })}
        title={t('enrichment.target_next', { defaultValue: '次のストローク' })}
        className={clsx(
          'flex items-center px-1 py-0.5 rounded-ss-sm',
          canNext
            ? 'text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]'
            : 'text-[var(--ss-t3)] opacity-40 cursor-not-allowed',
        )}
      >
        <MIcon name="chevron_right" size={14} />
      </button>
    </div>
  )
}
