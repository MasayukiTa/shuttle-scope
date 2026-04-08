/**
 * SearchableSelect — テキスト検索付きコンボボックス
 *
 * 選手・試合など項目数が増えるセレクターで使用。
 * ネイティブ <select> の代替として、テキスト入力でフィルタリング可能。
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { Search, X, ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'

export interface SearchableOption {
  value: string | number
  label: string
  /** 検索対象に含める補助テキスト（チーム名等） */
  searchText?: string
  /** ラベル左に表示するバッジ・アイコン */
  prefix?: string
  /** ラベル右に表示するサブ情報 */
  suffix?: string
}

interface SearchableSelectProps {
  options: SearchableOption[]
  value: string | number | null
  onChange: (value: string | number | null) => void
  placeholder?: string
  /** 未選択時の表示テキスト */
  emptyLabel?: string
  disabled?: boolean
  className?: string
  /** ドロップダウンの最大高さ */
  maxHeight?: number
  loading?: boolean
}

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = '検索...',
  emptyLabel = '— 選択 —',
  disabled = false,
  className,
  maxHeight = 240,
  loading = false,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlightIdx, setHighlightIdx] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const selectedOption = options.find((o) => o.value === value)

  // フィルタリング
  const filtered = query.trim()
    ? options.filter((o) => {
        const q = query.toLowerCase()
        return (
          o.label.toLowerCase().includes(q) ||
          (o.searchText && o.searchText.toLowerCase().includes(q)) ||
          (o.prefix && o.prefix.toLowerCase().includes(q)) ||
          (o.suffix && o.suffix.toLowerCase().includes(q))
        )
      })
    : options

  // 外部クリックで閉じる
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // 開いたときにフォーカス
  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus()
    }
  }, [open])

  // ハイライト位置をリセット
  useEffect(() => {
    setHighlightIdx(0)
  }, [query, open])

  // ハイライト位置が見えるようにスクロール
  useEffect(() => {
    if (!open || !listRef.current) return
    const items = listRef.current.querySelectorAll('[data-option]')
    items[highlightIdx]?.scrollIntoView({ block: 'nearest' })
  }, [highlightIdx, open])

  const handleSelect = useCallback(
    (val: string | number | null) => {
      onChange(val)
      setOpen(false)
      setQuery('')
    },
    [onChange],
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filtered[highlightIdx]) {
        handleSelect(filtered[highlightIdx].value)
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
      setQuery('')
    }
  }

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation()
    onChange(null)
    setQuery('')
  }

  return (
    <div ref={containerRef} className={clsx('relative', className)}>
      {/* トリガー */}
      <button
        type="button"
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        className={clsx(
          'flex items-center gap-2 w-full text-left rounded-md px-3 py-1.5 text-sm border transition-colors',
          'bg-gray-800 border-gray-700 hover:border-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500',
          disabled && 'opacity-50 cursor-not-allowed',
        )}
      >
        <span className={clsx('flex-1 truncate', !selectedOption && 'text-gray-500')}>
          {loading ? '読み込み中...' : selectedOption ? (
            <>
              {selectedOption.prefix && <span className="mr-1">{selectedOption.prefix}</span>}
              {selectedOption.label}
              {selectedOption.suffix && <span className="ml-1 text-gray-400 text-xs">{selectedOption.suffix}</span>}
            </>
          ) : emptyLabel}
        </span>
        {value != null && !disabled && (
          <X size={14} className="text-gray-500 hover:text-white shrink-0" onClick={handleClear} />
        )}
        <ChevronDown size={14} className={clsx('text-gray-500 shrink-0 transition-transform', open && 'rotate-180')} />
      </button>

      {/* ドロップダウン */}
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-gray-800 border border-gray-600 rounded-lg shadow-xl overflow-hidden">
          {/* 検索欄 */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-700">
            <Search size={14} className="text-gray-500 shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 outline-none"
            />
            {query && (
              <button onClick={() => setQuery('')} className="text-gray-500 hover:text-white">
                <X size={12} />
              </button>
            )}
          </div>

          {/* 選択肢リスト */}
          <div ref={listRef} className="overflow-y-auto" style={{ maxHeight }}>
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-sm text-gray-500 text-center">
                {query ? '該当なし' : '選択肢がありません'}
              </div>
            ) : (
              filtered.map((opt, idx) => (
                <button
                  key={opt.value}
                  data-option
                  type="button"
                  onClick={() => handleSelect(opt.value)}
                  className={clsx(
                    'flex items-center gap-2 w-full text-left px-3 py-2 text-sm transition-colors',
                    idx === highlightIdx
                      ? 'bg-blue-600/30 text-white'
                      : opt.value === value
                        ? 'bg-gray-700/50 text-white'
                        : 'text-gray-300 hover:bg-gray-700/50',
                  )}
                >
                  {opt.prefix && <span className="text-xs shrink-0">{opt.prefix}</span>}
                  <span className="flex-1 truncate">{opt.label}</span>
                  {opt.suffix && <span className="text-xs text-gray-500 shrink-0">{opt.suffix}</span>}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
