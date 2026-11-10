/**
 * MobileShareButton — 狭幅 (モバイル) ヘッダー右端に常時出すセッション共有ボタン。
 *
 * 背景 (2026-11-10 本番観察): 記録画面を幅 307px 等で開くと、上バーが折り返しきれず
 * 右端の ⋮ (overflow メニュー) ごと画面外に切れ、その中にしか無かった「共有」に
 * 到達できなかった。共有は記録画面の主要動線なので、⋮ に依存させず独立した
 * ボタンとして常時可視にする。ヘッダー側の flex-wrap と併せて、どの狭幅でも
 * 「共有」に必ず届くことを保証する。
 */
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

export interface MobileShareButtonProps {
  /** 既にセッションがあるときはそのコードを出し、タップでモーダルを開く。無ければ作成する。 */
  activeSessionCode?: string | null
  onOpenShare: () => void
  className?: string
}

export function MobileShareButton({ activeSessionCode, onOpenShare, className }: MobileShareButtonProps) {
  const { t } = useTranslation()
  const hasSession = activeSessionCode != null && activeSessionCode !== ''
  return (
    <button
      type="button"
      onClick={onOpenShare}
      aria-label={t('sharing.share')}
      title={t('sharing.share')}
      className={clsx(
        'flex items-center gap-1 px-2 py-1 rounded-ss-md text-xs font-medium transition-colors shrink-0',
        'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-3)]',
        className,
      )}
    >
      <MIcon name="share" size={14} aria-hidden="true" />
      <span className="font-mono font-bold max-w-[72px] truncate">
        {hasSession ? activeSessionCode : t('sharing.share')}
      </span>
    </button>
  )
}
