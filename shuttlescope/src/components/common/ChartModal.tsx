import { useEffect, ReactNode } from 'react'
import { X, LayoutDashboard } from 'lucide-react'

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
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/85 flex flex-col"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-900 shrink-0">
        <span className="text-white font-semibold text-base">{title}</span>
        <div className="flex items-center gap-3">
          {/* 元ダッシュボードへ戻るボタン */}
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 text-xs text-gray-300 hover:text-white bg-gray-700 hover:bg-gray-600 transition-colors px-3 py-1.5 rounded"
          >
            <LayoutDashboard size={13} />
            ダッシュボードへ戻る
          </button>
          {/* ✕ボタン */}
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-gray-700"
            title="閉じる (Esc)"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* チャートエリア */}
      <div className="flex-1 overflow-auto p-8 bg-gray-900">
        {children}
      </div>
    </div>
  )
}
