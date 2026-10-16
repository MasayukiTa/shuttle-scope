// 折り畳み可能なセクション。
//
// 同形のカードを縦に並べるだけだと「どれを見るべきか」が分からないため、
// 重要でないカード群をこの見出しの下に畳んで階層を作る。
//   - 閉じている間は子を描画しない (= 子の API 取得も走らない)
//   - 開閉は button (aria-expanded) で操作できる
//   - 開閉状態は画面内の一時状態。保存しない
import { ReactNode, useId, useState } from 'react'
import { MIcon } from '@/components/common/MIcon'

interface CollapsibleSectionProps {
  /** 見出し (翻訳済みの文字列) */
  title: string
  /** 見出し下の補足 (任意・翻訳済み) */
  description?: string
  /** 初期状態。既定は閉じる */
  defaultOpen?: boolean
  children: ReactNode
  className?: string
}

export function CollapsibleSection({
  title,
  description,
  defaultOpen = false,
  children,
  className = '',
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = useId()

  return (
    <section
      className={`rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] ${className}`}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left rounded-ss-lg hover:bg-[var(--ss-surface-2)] duration-base ease-out"
      >
        <MIcon name={open ? 'expand_less' : 'expand_more'} size={20} ariaHidden />
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-semibold text-[var(--ss-t1)]">{title}</span>
          {description && (
            <span className="block text-xs text-[var(--ss-t2)] mt-0.5">{description}</span>
          )}
        </span>
      </button>
      {open && (
        <div id={panelId} className="px-4 pb-4 space-y-4">
          {children}
        </div>
      )}
    </section>
  )
}
