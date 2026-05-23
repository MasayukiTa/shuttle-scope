/**
 * ResetConfirmModal — 会話リセット確認の小さいモーダル。
 * ESC でキャンセル、フォーカスは初期で Cancel に当てる。
 */
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

interface Props {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ResetConfirmModal({ open, onCancel, onConfirm }: Props) {
  const { t } = useTranslation()
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCancel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-confirm-title"
    >
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-4">
        <h3
          id="reset-confirm-title"
          className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3"
        >
          {t('auto.AdviceChat.reset_confirm')}
        </h3>
        <div className="flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            {t('auto.AdviceChat.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-sm rounded bg-red-600 hover:bg-red-700 text-white font-semibold"
          >
            {t('auto.AdviceChat.confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}
