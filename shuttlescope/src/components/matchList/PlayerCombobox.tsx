import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Player } from '@/types'
import { MIcon } from '@/components/common/MIcon'

// ─── 選手コンボボックス（名前検索 + 暫定登録対応）────────────────────────────
// MatchListPage から純粋抽出 (2026-05-21, god-file 分割フェーズ1)。
// 振る舞いは抽出前と完全に同一。

export interface PlayerComboboxProps {
  label: string
  required?: boolean
  value: number | ''
  query: string
  setQuery: (q: string) => void
  setValue: (id: number | '') => void
  candidates: Player[]
  isLight: boolean
  textSecondary: string
  placeholder?: string
}

export function PlayerCombobox({
  label, required = false, value, query, setQuery, setValue,
  candidates, isLight, textSecondary, placeholder = '名前を入力して検索...',
}: PlayerComboboxProps) {
  const { t } = useTranslation()

  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={containerRef}>
      <label className={`block text-sm ${textSecondary} mb-1`}>
        {label}{required && ' *'}
      </label>
      <div className="relative">
        <MIcon name="search" size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setValue('')
            setShowDropdown(true)
          }}
          onFocus={() => { if (query.trim().length >= 1) setShowDropdown(true) }}
          placeholder={placeholder}
          autoComplete="off"
          className={`w-full ${isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-700 border-gray-600 text-white'} border rounded pl-8 pr-3 py-2 text-sm`}
        />
        {value !== '' && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
            <MIcon name="person" size={12} className="text-green-400" />
            <span className="text-[10px] text-green-400">{t('auto.MatchListPage.k1')}</span>
          </div>
        )}
      </div>
      {showDropdown && query.trim().length >= 1 && (
        <div className={`absolute z-20 top-full mt-1 w-full ${isLight ? 'bg-white border-gray-300' : 'bg-gray-700 border-gray-600'} border rounded shadow-lg max-h-40 overflow-y-auto`}>
          {candidates.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setValue(p.id)
                setQuery(p.name)
                setShowDropdown(false)
              }}
              className={`w-full text-left px-3 py-2 ${isLight ? 'hover:bg-gray-100' : 'hover:bg-gray-600'} text-sm flex items-center gap-2 min-w-0`}
            >
              <MIcon name="person" size={12} className="text-gray-400 shrink-0" />
              <span className="truncate">{p.name}</span>
              {p.team && (
                <span className="text-xs text-blue-300 bg-blue-900/30 px-1.5 rounded shrink-0">{p.team}</span>
              )}
              {p.needs_review && <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded shrink-0">{t('match.list.tentative')}</span>}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setValue('')
              setShowDropdown(false)
            }}
            className={`w-full text-left px-3 py-2 hover:bg-blue-500/10 text-sm flex items-center gap-2 text-blue-400 border-t ${isLight ? 'border-gray-200' : 'border-gray-600'}`}
          >
            <MIcon name="person_add" size={12} className="shrink-0" />
            <span>{t('match.list.create_tentative', { name: query.trim(), defaultValue: 'Create "{{name}}" as tentative' })}</span>
          </button>
        </div>
      )}
    </div>
  )
}
