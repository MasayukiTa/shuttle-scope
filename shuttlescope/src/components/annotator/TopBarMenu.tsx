/**
 * U1: AnnotatorPage 上バー圧縮用ドロップダウンメニュー。
 *
 * 二次操作 (試合中モード切替、annotation モード切替、例外終了、dual monitor、
 * in-match panel toggle、TrackNet/YOLO バッチ操作 etc) を ⋮ ボタン直下に
 * 折りたたんで上バーを軽くする。
 *
 * 振る舞い:
 *  - ⋮ クリックで開閉
 *  - 外側クリック / Esc で閉じる
 *  - children をそのまま並べる (button や inline JSX をそのまま渡せる)
 *  - <TopBarMenuSection title="…"> でセクション見出し付きのグループに整理可能
 */
import { ReactNode, useEffect, useRef, useState } from 'react'
import { MoreVertical } from 'lucide-react'
import { clsx } from 'clsx'

interface TopBarMenuProps {
  children: ReactNode
  /** ボタン aria-label */
  ariaLabel?: string
  className?: string
}

export function TopBarMenu({ children, ariaLabel = 'メニュー', className }: TopBarMenuProps) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={wrapperRef} className={clsx('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        aria-expanded={open}
        className="flex items-center justify-center w-8 h-8 rounded text-gray-300 hover:bg-gray-700 transition-colors"
      >
        <MoreVertical size={18} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 min-w-[260px] max-w-[340px] bg-gray-800 border border-gray-700 rounded-md shadow-2xl py-2"
          role="menu"
          onClick={() => setOpen(false)}
        >
          <div className="flex flex-col gap-2 px-2">
            {children}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * メニュー内セクション。見出し + 区切り線 + 子ボタン。
 * 同種の操作 (記録モード / 表示 / 危険操作) をグループ化する用途。
 */
interface TopBarMenuSectionProps {
  title: string
  children: ReactNode
  /** 一番最初のセクションは上区切り線を出さない */
  firstSection?: boolean
}

export function TopBarMenuSection({ title, children, firstSection = false }: TopBarMenuSectionProps) {
  return (
    <div className="flex flex-col gap-1">
      {!firstSection && <div className="border-t border-gray-700 -mx-2 mt-1 mb-1" />}
      <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 px-1 pt-0.5">
        {title}
      </div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  )
}
