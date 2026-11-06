import { useTranslation } from 'react-i18next'

/**
 * 無操作が続いて自動ログアウトが近づいたときに出す警告ダイアログ。
 *
 * - このダイアログが出た時点で、入力中のラリーは既に一時保存へ退避済み
 *   (App 側が warn と同時に autosave-flush を投げる)。なのでここで何もしなくても
 *   入力は失われない。ダイアログは「このまま放置すると自動でログアウトする」ことと、
 *   続ける手段を知らせるためのもの。
 * - 「作業を続ける」を押す / 画面のどこかを操作すると猶予が取り消される。
 * - 残り秒数はカウントダウンで見せる。
 */
export interface IdleWarningDialogProps {
  /** 自動ログアウトまでの残り秒数 (カウントダウン表示用)。 */
  remainingSec: number
  /** 作業を続ける (猶予を取り消してセッションを維持)。 */
  onStay: () => void
  /** 今すぐログアウトする。 */
  onLogoutNow: () => void
}

export function IdleWarningDialog({ remainingSec, onStay, onLogoutNow }: IdleWarningDialogProps) {
  const { t } = useTranslation()
  const sec = Math.max(0, Math.floor(remainingSec))
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 px-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="idle-warning-title"
      aria-describedby="idle-warning-body"
    >
      <div className="w-full max-w-sm rounded-lg bg-[var(--ss-surface-1,#1f2937)] p-5 shadow-xl">
        <h2
          id="idle-warning-title"
          className="text-lg font-bold text-[var(--ss-t1,#f9fafb)]"
        >
          {t('auth.idle_warning.title', { defaultValue: 'まもなく自動的にログアウトします' })}
        </h2>
        <p id="idle-warning-body" className="mt-2 text-sm text-[var(--ss-t2,#9ca3af)]">
          {t('auth.idle_warning.body', {
            defaultValue:
              'しばらく操作がなかったため、あと{{sec}}秒で自動的にログアウトします。入力中のラリーは一時保存してありますので、ログアウトしても次回ログイン時に復元できます。作業を続けるには「作業を続ける」を押してください。',
            sec,
          })}
        </p>
        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            onClick={onStay}
            className="w-full rounded bg-blue-700 px-3 py-2 text-sm text-white hover:bg-blue-600"
          >
            {t('auth.idle_warning.stay', { defaultValue: '作業を続ける' })}
          </button>
          <button
            type="button"
            onClick={onLogoutNow}
            className="w-full rounded px-3 py-2 text-sm text-gray-400 hover:text-gray-200"
          >
            {t('auth.idle_warning.logout_now', { defaultValue: '今すぐログアウト' })}
          </button>
        </div>
      </div>
    </div>
  )
}

export default IdleWarningDialog
