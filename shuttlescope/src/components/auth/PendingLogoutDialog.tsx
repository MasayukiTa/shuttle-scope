import { useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * G4 #529: モバイルアノテータで未送信ラリーがあるまま明示的にログアウトしようとした
 * ときに出す確認ダイアログ。send / keep / delete / cancel の 4 択。
 *
 * 振る舞い (呼び出し側の App.tsx が実装):
 *   - send   : 先に送信を試み、完了するまでログアウトしない。失敗したら
 *              エラーを出してデータを保持 (onSend が reject する)。
 *   - keep   : 送らずにログアウト (データは端末に残る)。
 *   - delete : 確認のあとに本人のデータだけを消してからログアウト。
 *   - cancel : ログアウトをやめる。
 *
 * このコンポーネントは UI と確認フローだけを持ち、IndexedDB / 送信 / ログアウト
 * 自体は props のコールバックに任せる。
 */
export interface PendingLogoutDialogProps {
  /** 未送信件数 (表示用)。 */
  pendingCount: number
  /** 送信してからログアウト。失敗したら reject すること。 */
  onSend: () => Promise<void>
  /** 送らずに残してログアウト。 */
  onKeep: () => void
  /** 本人のデータを消してログアウト (確認済みのときだけ呼ばれる)。 */
  onDelete: () => Promise<void>
  /** ログアウトをやめる。 */
  onCancel: () => void
}

export function PendingLogoutDialog({
  pendingCount,
  onSend,
  onKeep,
  onDelete,
  onCancel,
}: PendingLogoutDialogProps) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSend = async () => {
    setBusy(true)
    setError(null)
    try {
      await onSend()
    } catch {
      // 送信失敗: データは残し、ログアウトしない。
      setError(t('auth.pending_error'))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!confirmingDelete) {
      setConfirmingDelete(true)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onDelete()
    } catch {
      setError(t('auth.pending_error'))
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pending-logout-title"
    >
      <div className="w-full max-w-sm rounded-lg bg-[var(--ss-surface-1,#1f2937)] p-5 shadow-xl">
        <h2
          id="pending-logout-title"
          className="text-lg font-bold text-[var(--ss-t1,#f9fafb)]"
        >
          {t('auth.pending_logout_title')}
        </h2>
        <p className="mt-2 text-sm text-[var(--ss-t2,#9ca3af)]">
          {t('auth.pending_logout_body', { count: pendingCount })}
        </p>

        {error && (
          <p className="mt-3 text-sm text-red-400" role="alert">
            {error}
          </p>
        )}

        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            onClick={handleSend}
            disabled={busy}
            className="w-full rounded bg-blue-700 px-3 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            {t('auth.pending_send')}
          </button>
          <button
            type="button"
            onClick={onKeep}
            disabled={busy}
            className="w-full rounded bg-gray-700 px-3 py-2 text-sm text-gray-100 hover:bg-gray-600 disabled:opacity-50"
          >
            {t('auth.pending_keep')}
          </button>
          <button
            type="button"
            onClick={handleDelete}
            disabled={busy}
            className="w-full rounded border border-red-500 px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 disabled:opacity-50"
          >
            {confirmingDelete ? t('auth.pending_delete_confirm') : t('auth.pending_delete')}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="w-full rounded px-3 py-2 text-sm text-gray-400 hover:text-gray-200 disabled:opacity-50"
          >
            {t('auth.pending_cancel')}
          </button>
        </div>
      </div>
    </div>
  )
}

export default PendingLogoutDialog
