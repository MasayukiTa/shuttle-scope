import { useEffect, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface ChartModalProps {
  title: string
  onClose: () => void
  children: ReactNode
}

/**
 * グラフ全画面表示モーダル。
 * - Esc キーまたはオーバーレイクリックで閉じる
 * - 「元ダッシュボードへ戻る」ボタンで閉じる
 */
export function ChartModal({ title, onClose, children }: ChartModalProps) {
  const { t } = useTranslation()

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-[var(--ss-bg-overlay)] flex flex-col"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-[var(--ss-border)] bg-[var(--ss-surface-1)] shadow-pop shrink-0">
        <span className="text-[var(--ss-t1)] font-semibold text-base">{title}</span>
        <div className="flex items-center gap-3">
          {/* 元ダッシュボードへ戻るボタン */}
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 text-xs text-[var(--ss-t2)] hover:text-[var(--ss-t1)] bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] transition-colors duration-fast ease-out px-3 py-1.5 rounded-ss-md"
          >
            <MIcon name="dashboard" size={13} />
            {t('auto.ChartModal.back_to_dashboard')}
          </button>
          {/* close ボタン */}
          <button
            onClick={onClose}
            className="text-[var(--ss-t3)] hover:text-[var(--ss-t1)] transition-colors duration-fast ease-out p-1 rounded-ss-md hover:bg-[var(--ss-surface-2)]"
            title={t('auto.ChartModal.k1')}
          >
            <MIcon name="close" size={18} />
          </button>
        </div>
      </div>

      {/* チャートエリア: 横長グラフは横最大、縦長グラフは縦最大まで展開 */}
      <div className="flex-1 overflow-auto bg-[var(--ss-bg-app)]">
        <div className="min-h-full flex items-center justify-center p-6">
          <div className="w-full">
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
