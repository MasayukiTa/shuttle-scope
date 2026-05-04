/**
 * U6: Ctrl+K コマンドパレット (VS Code / Linear 風)。
 *
 * 任意のアクションを名前で検索 → Enter で実行。
 *
 * - グローバルキー: Ctrl+K (Mac は Cmd+K も)
 * - 開いた状態で / でも検索フォーカス
 * - 矢印キーで候補移動、Enter で実行、Esc で閉じる
 * - command provider は外部から `commands` props で注入する
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'

export interface PaletteCommand {
  id: string
  label: string
  hint?: string         // 補足 (右側にグレー表示)
  icon?: string         // Material Symbols name
  keywords?: string[]   // 検索ヒット用
  run: () => void
  disabled?: boolean
}

interface CommandPaletteProps {
  commands: PaletteCommand[]
}

export function CommandPalette({ commands }: CommandPaletteProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIdx, setActiveIdx] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // グローバルキー Ctrl+K / Cmd+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.ctrlKey || e.metaKey
      if (meta && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setOpen((v) => !v)
        setQuery('')
        setActiveIdx(0)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 開いたら入力にフォーカス
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 30)
      return () => clearTimeout(t)
    }
  }, [open])

  const q = query.trim().toLowerCase()
  const filtered = useMemo(() => {
    if (!q) return commands
    return commands.filter((c) => {
      const hay = (c.label + ' ' + (c.hint ?? '') + ' ' + (c.keywords ?? []).join(' ')).toLowerCase()
      return hay.includes(q)
    })
  }, [commands, q])

  // active index clamp
  useEffect(() => { setActiveIdx(0) }, [q])

  const close = () => { setOpen(false); setQuery('') }
  const exec = (c: PaletteCommand) => {
    if (c.disabled) return
    close()
    // run after close so any side-effect-on-close is settled
    setTimeout(c.run, 0)
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm"
      onClick={close}
      role="dialog"
      aria-modal="true"
      aria-label="コマンドパレット"
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-lg shadow-2xl w-[520px] max-w-[90vw] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-700">
          <MIcon name="search" size={18} className="text-gray-500" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActiveIdx((i) => Math.min(filtered.length - 1, i + 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActiveIdx((i) => Math.max(0, i - 1))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                const c = filtered[activeIdx]
                if (c) exec(c)
              } else if (e.key === 'Escape') {
                close()
              }
            }}
            placeholder="アクションを検索 (例: 次のラリー / セット終了)"
            className="flex-1 bg-transparent text-gray-100 outline-none text-sm placeholder:text-gray-500"
          />
          <kbd className="text-[10px] text-gray-500 border border-gray-700 rounded px-1.5 py-0.5">
            Esc
          </kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto py-1" role="listbox">
          {filtered.length === 0 && (
            <li className="px-3 py-3 text-xs text-gray-500">該当なし</li>
          )}
          {filtered.map((c, i) => (
            <li
              key={c.id}
              role="option"
              aria-selected={i === activeIdx}
              onMouseEnter={() => setActiveIdx(i)}
              onClick={() => exec(c)}
              className={clsx(
                'flex items-center gap-2 px-3 py-1.5 cursor-pointer text-sm',
                i === activeIdx ? 'bg-blue-600 text-white' : 'text-gray-200',
                c.disabled && 'opacity-40 cursor-not-allowed',
              )}
            >
              {c.icon && <MIcon name={c.icon} size={16} />}
              <span className="flex-1 truncate">{c.label}</span>
              {c.hint && <span className="text-[10px] text-gray-400">{c.hint}</span>}
            </li>
          ))}
        </ul>
        <div className="flex items-center justify-between px-3 py-1.5 border-t border-gray-700 text-[10px] text-gray-500">
          <span>↑↓ 選択 / Enter 実行</span>
          <span>Ctrl+K でいつでも</span>
        </div>
      </div>
    </div>
  )
}
