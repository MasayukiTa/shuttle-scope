/**
 * 所有者不明の退避ラリーがある間、閉じられない警告を出す (S-14)。
 * 件数が 0 になるまで (送信確認 or 破棄) 消えない。送る操作はユーザーが分かっている時だけ有効。
 */
import { useTranslation } from 'react-i18next'

interface Props {
  count: number
  userKnown: boolean
  onClaim: () => void
  onDiscard: () => void
}

export function UnownedRallyBanner({ count, userKnown, onClaim, onDiscard }: Props) {
  const { t } = useTranslation()
  if (count <= 0) return null
  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid="unowned-rally-banner"
      className="fixed left-1/2 -translate-x-1/2 top-2 z-[190] max-w-[min(94vw,640px)] px-4 py-2 rounded-ss-lg border shadow-pop text-sm bg-[var(--ss-warning-bg)] border-[var(--ss-warning-border)] text-[var(--ss-warning-text)]"
    >
      <div className="whitespace-pre-line break-words">
        {t(userKnown ? 'annotator.unowned_rally_warning' : 'annotator.unowned_rally_warning_login', { n: count })}
      </div>
      <div className="mt-2 flex gap-2 justify-end">
        <button
          type="button"
          onClick={onClaim}
          disabled={!userKnown}
          className="px-3 py-1 rounded border border-current disabled:opacity-40"
        >
          {t('annotator.unowned_rally_claim')}
        </button>
        <button
          type="button"
          onClick={onDiscard}
          className="px-3 py-1 rounded border border-current"
        >
          {t('annotator.unowned_rally_discard')}
        </button>
      </div>
    </div>
  )
}
