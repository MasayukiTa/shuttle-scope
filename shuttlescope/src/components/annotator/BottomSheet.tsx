/**
 * U7: モバイル用ボトムシート (右パネル代替)。
 *
 * 768px 未満で右パネルを bottom-sheet として表示する。
 *  - デフォルトは折り畳み (タップで展開)
 *  - 展開時 max-h は viewport の 70%
 *  - children に既存の右パネル内容を渡す
 *  - drag handle で上下スワイプ展開/折り畳み (タップ展開も可)
 */
import { ReactNode, useEffect, useState } from 'react'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'

interface BottomSheetProps {
  /** 表示中ラベル (例 '入力 / 確認 / 解析 / 設定') */
  label?: string
  children: ReactNode
  /** 初期 open 状態 */
  defaultOpen?: boolean
}

export function BottomSheet({ label, children, defaultOpen = false }: BottomSheetProps) {
  const [open, setOpen] = useState(defaultOpen)

  // Esc で閉じる
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div
      className={clsx(
        'fixed left-0 right-0 bottom-0 z-30 bg-gray-900 border-t border-gray-700 shadow-2xl transition-transform duration-200',
        open ? 'translate-y-0' : 'translate-y-[calc(100%-44px)]',
      )}
      style={{ maxHeight: '78vh' }}
      role="region"
      aria-label="ボトムシート"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-gray-300 hover:bg-gray-800 active:bg-gray-700"
        aria-expanded={open}
      >
        <span className="block w-10 h-1 rounded bg-gray-600" />
        {label && <span className="ml-2">{label}</span>}
        <MIcon name={open ? 'expand_more' : 'expand_less'} size={16} />
      </button>
      {open && (
        <div className="overflow-y-auto" style={{ maxHeight: 'calc(78vh - 44px)' }}>
          {children}
        </div>
      )}
    </div>
  )
}
