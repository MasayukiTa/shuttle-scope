/**
 * PlayerSelectorSheet — 汎用「選手選択」ボトムシート (モバイル) / 軽量モーダル (デスクトップ)。
 *
 * 既存 BottomSheet が AnnotatorPage 専用に作られていたため、
 * 他ページからも選手選択を mobile-first で再利用できるよう抽出した。
 *
 * 機能:
 *   - 選手リスト + 検索インクリメンタルフィルタ
 *   - 選択でただちに onSelect(player) が呼ばれシートが閉じる
 *   - lg 以上では中央モーダル風、md 未満では下からせり上がるシート
 *
 * 使用側責任:
 *   - players は呼び出し側で fetch して渡す (本コンポーネントは fetch しない)
 *   - keyboard navigation (↑/↓/Enter) は今回 scope 外。focus は最初の項目に当てる
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useBreakpoint } from '@/hooks/useBreakpoint'

export interface PlayerOption {
  id: number
  name: string
  team?: string | null
}

interface PlayerSelectorSheetProps {
  open: boolean
  onClose: () => void
  players: PlayerOption[]
  selectedId?: number | null
  onSelect: (player: PlayerOption) => void
  title?: string
  /** チーム名を 2 行目で表示する */
  showTeam?: boolean
}

export function PlayerSelectorSheet({
  open,
  onClose,
  players,
  selectedId,
  onSelect,
  title,
  showTeam = true,
}: PlayerSelectorSheetProps) {
  const { t } = useTranslation()
  const { atLeast } = useBreakpoint()
  const isDesktop = atLeast('md')
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // 開いたら検索ボックスにフォーカス、閉じたらクエリリセット
  useEffect(() => {
    if (open) {
      const id = window.setTimeout(() => inputRef.current?.focus(), 80)
      return () => window.clearTimeout(id)
    }
    setQuery('')
  }, [open])

  // Esc で閉じる
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return players
    return players.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.team ?? '').toLowerCase().includes(q),
    )
  }, [players, query])

  if (!open) return null

  const headerLabel = title ?? t('common.player_selector_title', { defaultValue: '選手を選択' })

  // モバイル: 下からせり上がるボトムシート / デスクトップ: 中央モーダル
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={headerLabel}
      className="fixed inset-0 z-40"
      onClick={(e) => {
        // backdrop タップで閉じる (シート本体は stopPropagation)
        if (e.currentTarget === e.target) onClose()
      }}
    >
      {/* バックドロップ */}
      <div className="absolute inset-0 bg-black/40" />

      <div
        onClick={(e) => e.stopPropagation()}
        className={clsx(
          'absolute bg-gray-900 text-gray-100 shadow-2xl border-gray-700 flex flex-col',
          isDesktop
            ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[480px] max-h-[70vh] rounded-lg border'
            : 'left-0 right-0 bottom-0 max-h-[80vh] rounded-t-lg border-t',
        )}
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        {/* drag handle (モバイルのみ) */}
        {!isDesktop && (
          <div className="flex justify-center pt-2">
            <span className="block w-10 h-1 rounded bg-gray-600" aria-hidden />
          </div>
        )}

        <header className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <h2 className="text-sm font-medium">{headerLabel}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: '閉じる' })}
            className="text-gray-400 hover:text-white text-lg leading-none px-2"
          >
            ×
          </button>
        </header>

        <div className="px-4 py-2 border-b border-gray-700">
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('common.player_selector_search', { defaultValue: '名前またはチームで検索' })}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="overflow-y-auto flex-1">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-gray-500">
              {t('common.player_selector_empty', { defaultValue: '該当する選手がいません' })}
            </div>
          ) : (
            <ul className="divide-y divide-gray-800">
              {filtered.map((p) => {
                const isSelected = selectedId === p.id
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(p)
                        onClose()
                      }}
                      className={clsx(
                        'w-full text-left px-4 py-3 hover:bg-gray-800 active:bg-gray-700 flex flex-col gap-0.5',
                        isSelected && 'bg-blue-900/40',
                      )}
                      aria-pressed={isSelected}
                    >
                      <span className="text-sm font-medium">{p.name}</span>
                      {showTeam && p.team && (
                        <span className="text-xs text-gray-400">{p.team}</span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
