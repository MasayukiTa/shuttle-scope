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
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

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
  const { t } = useTranslation()

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

  // 半透明の飽和塗りではなく、白/サーフェス地 + hairline + 左アクセントで意味を運ぶ。
  const palette = notice.kind === 'error'
    ? 'bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]'
    : notice.kind === 'warn'
      ? 'bg-[var(--ss-warning-bg)] border-[var(--ss-warning-border)] text-[var(--ss-warning-text)]'
      : 'bg-[var(--ss-info-bg)] border-[var(--ss-info-border)] text-[var(--ss-info-text)]'

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="fixed left-1/2 -translate-x-1/2 bottom-6 z-[200] max-w-[min(90vw,520px)] px-2"
      style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
    >
      <div className={clsx('flex items-start gap-3 px-4 py-3 rounded-ss-lg border shadow-pop transition-opacity duration-base ease-out', palette)}>
        <span className="shrink-0 text-base leading-none">
          <MIcon name={notice.kind === 'error' ? 'error' : notice.kind === 'warn' ? 'warning' : 'info'} size={18} />
        </span>
        <div className="flex-1 text-sm whitespace-pre-line break-words min-w-0">
          {notice.message}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t('auto.Notice.k1')}
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
      className="fixed inset-0 z-[210] flex items-center justify-center bg-[var(--ss-bg-overlay)] px-3"
      onClick={(e) => { if (e.currentTarget === e.target) cancel() }}
    >
      <div className="bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-pop max-w-md w-full">
        {pending.title && (
          <header className="px-4 py-3 border-b border-[var(--ss-border)] text-sm font-medium text-[var(--ss-t1)]">
            {pending.title}
          </header>
        )}
        <div className="px-4 py-4 text-sm text-[var(--ss-t2)] whitespace-pre-line break-words">
          {pending.message}
        </div>
        <footer className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[var(--ss-border)]">
          <button
            type="button"
            onClick={cancel}
            className="px-3 py-1.5 rounded-ss-md text-sm bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] hover:bg-[var(--ss-surface-2)] text-[var(--ss-t1)] transition-colors duration-fast ease-out"
          >
            {pending.cancelLabel ?? 'キャンセル'}
          </button>
          <button
            type="button"
            onClick={confirm}
            autoFocus
            className={clsx(
              'px-3 py-1.5 rounded-ss-md text-sm font-medium transition-colors duration-fast ease-out',
              pending.destructive
                ? 'bg-[var(--ss-bad)] hover:opacity-90 text-white'
                : 'bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white',
            )}
          >
            {pending.confirmLabel ?? 'OK'}
          </button>
        </footer>
      </div>
    </div>
  )
}
