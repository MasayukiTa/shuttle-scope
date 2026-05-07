/**
 * Notice / ConfirmDialog — alert() / window.confirm() の共通スタイル付き代替。
 *
 * 設計指針:
 * - JS 同期実行をブロックする native alert/confirm の代わりに React state で制御
 * - ESC / バックドロップクリックでキャンセル
 * - ConfirmDialog は破壊的操作 (削除など) で確認ボタンを赤系で目立たせる
 */
import { useEffect } from 'react'
import { clsx } from 'clsx'

export interface NoticeState {
  kind: 'error' | 'info' | 'warn'
  message: string
  /** 表示秒数 (auto-dismiss)。0 を指定すると手動 close まで残す */
  durationMs?: number
}

interface NoticeBannerProps {
  notice: NoticeState | null
  onDismiss: () => void
}

/**
 * 画面下部に表示するトースト型エラー/通知バナー。
 * `notice` が null なら描画しない。
 */
export function NoticeBanner({ notice, onDismiss }: NoticeBannerProps) {
  // auto-dismiss
  useEffect(() => {
    if (!notice) return
    const ms = notice.durationMs ?? (notice.kind === 'error' ? 8000 : 4000)
    if (ms <= 0) return
    const id = window.setTimeout(onDismiss, ms)
    return () => window.clearTimeout(id)
  }, [notice, onDismiss])

  // ESC で閉じる
  useEffect(() => {
    if (!notice) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [notice, onDismiss])

  if (!notice) return null

  const palette = notice.kind === 'error'
    ? 'bg-red-900/95 border-red-500 text-red-100'
    : notice.kind === 'warn'
      ? 'bg-amber-900/95 border-amber-500 text-amber-100'
      : 'bg-blue-900/95 border-blue-500 text-blue-100'

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed left-1/2 -translate-x-1/2 bottom-6 z-[200] max-w-[min(90vw,520px)] px-2"
      style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
    >
      <div className={clsx('flex items-start gap-3 px-4 py-3 rounded-lg border shadow-2xl', palette)}>
        <span className="shrink-0 text-base leading-none">
          {notice.kind === 'error' ? '⚠' : notice.kind === 'warn' ? '!' : 'ⓘ'}
        </span>
        <div className="flex-1 text-sm whitespace-pre-line break-words min-w-0">
          {notice.message}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="閉じる"
          className="shrink-0 text-lg leading-none opacity-70 hover:opacity-100 px-1"
        >
          ×
        </button>
      </div>
    </div>
  )
}

export interface ConfirmState {
  title?: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  /** 破壊的操作なら true (確認ボタンが赤系になる) */
  destructive?: boolean
  onConfirm: () => void
  onCancel?: () => void
}

interface ConfirmDialogProps {
  pending: ConfirmState | null
  onClose: () => void
}

/**
 * モーダル確認ダイアログ。`window.confirm()` の代替。
 * バックドロップクリック / ESC でキャンセル扱い (onCancel が呼ばれる)。
 */
export function ConfirmDialog({ pending, onClose }: ConfirmDialogProps) {
  useEffect(() => {
    if (!pending) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        pending.onCancel?.()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending, onClose])

  if (!pending) return null

  const cancel = () => {
    pending.onCancel?.()
    onClose()
  }
  const confirm = () => {
    pending.onConfirm()
    onClose()
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={pending.title ?? '確認'}
      className="fixed inset-0 z-[210] flex items-center justify-center bg-black/60 backdrop-blur-sm px-3"
      onClick={(e) => { if (e.currentTarget === e.target) cancel() }}
    >
      <div className="bg-gray-900 border border-gray-700 rounded-lg shadow-2xl max-w-md w-full">
        {pending.title && (
          <header className="px-4 py-3 border-b border-gray-700 text-sm font-medium text-gray-100">
            {pending.title}
          </header>
        )}
        <div className="px-4 py-4 text-sm text-gray-200 whitespace-pre-line break-words">
          {pending.message}
        </div>
        <footer className="flex items-center justify-end gap-2 px-4 py-3 border-t border-gray-700">
          <button
            type="button"
            onClick={cancel}
            className="px-3 py-1.5 rounded text-sm bg-gray-700 hover:bg-gray-600 text-gray-200"
          >
            {pending.cancelLabel ?? 'キャンセル'}
          </button>
          <button
            type="button"
            onClick={confirm}
            autoFocus
            className={clsx(
              'px-3 py-1.5 rounded text-sm font-medium',
              pending.destructive
                ? 'bg-red-700 hover:bg-red-600 text-white'
                : 'bg-blue-600 hover:bg-blue-500 text-white',
            )}
          >
            {pending.confirmLabel ?? 'OK'}
          </button>
        </footer>
      </div>
    </div>
  )
}
