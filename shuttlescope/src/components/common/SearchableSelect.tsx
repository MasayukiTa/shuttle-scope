/**
 * SearchableSelect — テキスト検索付きコンボボックス
 *
 * 選手・試合など項目数が増えるセレクターで使用。
 * ネイティブ <select> の代替として、テキスト入力でフィルタリング可能。
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'

export interface SearchableOption {
  value: string | number
  label: string
  /** 検索対象に含める補助テキスト（チーム名等） */
  searchText?: string
  /** ラベル左に表示するバッジ・アイコン (Material Symbols name) */
  prefix?: string
  /** prefix を MIcon として描画するかどうか (true: <MIcon name={prefix} />, false: text) */
  prefixIsIcon?: boolean
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
  /** ドロップダウンの開き方向（right = 右端基準で左に展開） */
  dropdownAlign?: 'left' | 'right'
}

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder,
  emptyLabel,
  disabled = false,
  className,
  maxHeight = 240,
  loading = false,
  dropdownAlign = 'left',
}: SearchableSelectProps) {
  const { t } = useTranslation()
  const effectivePlaceholder = placeholder ?? t('common.search_placeholder', 'Search...')
  const effectiveEmptyLabel = emptyLabel ?? t('common.select_placeholder', '— Select —')
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
          'flex items-center gap-2 w-full text-left rounded-ss-md px-3 py-1.5 text-sm border transition-colors duration-fast ease-out',
          'bg-[var(--ss-ctrl-bg)] border-[var(--ss-ctrl-border)] hover:border-[var(--ss-ctrl-border-hover)]',
          'focus:outline-none focus:border-[var(--ss-ctrl-border-focus)] focus:ring-[3px] focus:ring-[var(--ss-focus-ring)]',
          disabled && 'opacity-50 cursor-not-allowed',
        )}
      >
        <span className={clsx('flex-1 truncate', !selectedOption ? 'text-[var(--ss-ctrl-placeholder)]' : 'text-[var(--ss-ctrl-text)]')}>
          {loading ? t('common.loading', 'Loading...') : selectedOption ? (
            <>
              {selectedOption.prefix && (
                selectedOption.prefixIsIcon
                  ? <MIcon name={selectedOption.prefix} size={12} className="mr-1 inline" />
                  : <span className="mr-1">{selectedOption.prefix}</span>
              )}
              {selectedOption.label}
              {selectedOption.suffix && <span className="ml-1 text-[var(--ss-t3)] text-xs">{selectedOption.suffix}</span>}
            </>
          ) : effectiveEmptyLabel}
        </span>
        {value != null && !disabled && (
          <MIcon name="close" size={14} className="text-[var(--ss-t3)] hover:text-[var(--ss-t1)] shrink-0" onClick={handleClear} />
        )}
        <MIcon name="expand_more" size={14} className={clsx('text-[var(--ss-t3)] shrink-0 transition-transform duration-fast ease-out', open && 'rotate-180')} />
      </button>

      {/* ドロップダウン */}
      {open && (
        <div className={clsx('absolute z-50 mt-1 w-full bg-[var(--ss-surface-1)] border border-[var(--ss-border)] rounded-ss-lg shadow-pop overflow-hidden min-w-[200px]', dropdownAlign === 'right' ? 'right-0' : 'left-0')}>
          {/* 検索欄 */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--ss-border)]">
            <MIcon name="search" size={14} className="text-[var(--ss-t3)] shrink-0" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={effectivePlaceholder}
              className="flex-1 bg-transparent text-sm text-[var(--ss-ctrl-text)] placeholder-[var(--ss-ctrl-placeholder)] outline-none"
            />
            {query && (
              <button onClick={() => setQuery('')} className="text-[var(--ss-t3)] hover:text-[var(--ss-t1)]">
                <MIcon name="close" size={12} />
              </button>
            )}
          </div>

          {/* 選択肢リスト */}
          <div ref={listRef} className="overflow-y-auto" style={{ maxHeight }}>
            {filtered.length === 0 ? (
              <div className="px-3 py-3 text-sm text-[var(--ss-t3)] text-center">
                {query ? t('common.no_matches', 'No matches') : t('common.no_options', 'No options')}
              </div>
            ) : (
              filtered.map((opt, idx) => (
                <button
                  key={opt.value}
                  data-option
                  type="button"
                  onClick={() => handleSelect(opt.value)}
                  className={clsx(
                    'flex items-center gap-2 w-full text-left px-3 py-2 text-sm transition-colors duration-fast ease-out',
                    idx === highlightIdx
                      ? 'bg-[var(--ss-brand-tint)] text-[var(--ss-t1)]'
                      : opt.value === value
                        ? 'bg-[var(--ss-surface-2)] text-[var(--ss-t1)]'
                        : 'text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]',
                  )}
                >
                  {opt.prefix && (
                    opt.prefixIsIcon
                      ? <MIcon name={opt.prefix} size={12} className="shrink-0" />
                      : <span className="text-xs shrink-0">{opt.prefix}</span>
                  )}
                  <span className="flex-1 truncate">{opt.label}</span>
                  {opt.suffix && <span className="text-xs text-[var(--ss-t3)] shrink-0">{opt.suffix}</span>}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
