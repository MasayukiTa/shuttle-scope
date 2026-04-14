import { useEffect, useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useTheme } from '@/hooks/useTheme'
import { UserRole } from '@/types'

// 選手ロール選択時に player_id、コーチロール選択時に team_name を収集する共通ピッカー
// - onSelect は完了時のみ呼ばれる（キャンセル時は onCancel）
// - inline=true ならフル画面表示（初回起動用）、false なら対象ロール固定でピッカー部のみ
export type RolePickerStage =
  | { kind: 'roles' }
  | { kind: 'player' }
  | { kind: 'team' }

export function RolePicker({
  mode,
  initialStage,
  onSelect,
  onCancel,
}: {
  mode: 'initial' | 'modal'
  initialStage?: RolePickerStage
  onSelect: (role: UserRole, playerId?: number | null, teamName?: string | null) => void
  onCancel?: () => void
}) {
  const { t } = useTranslation()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [stage, setStage] = useState<RolePickerStage>(initialStage ?? { kind: 'roles' })
  const [players, setPlayers] = useState<Array<{ id: number; name: string; team: string | null }> | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const needsPlayers = stage.kind === 'player' || stage.kind === 'team'

  useEffect(() => {
    if (!needsPlayers) return
    let cancelled = false
    setLoadErr(null)
    fetch('/api/players')
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((res) => {
        if (cancelled) return
        setPlayers((res?.data ?? []) as Array<{ id: number; name: string; team: string | null }>)
      })
      .catch((e) => { if (!cancelled) setLoadErr(`選手一覧の取得に失敗: ${e}`) })
    return () => { cancelled = true }
  }, [needsPlayers])

  const filteredPlayers = (players ?? []).filter((p) =>
    !search.trim() || p.name.toLowerCase().includes(search.trim().toLowerCase())
  )

  const teams = useMemo(() => {
    const set = new Set<string>()
    for (const p of (players ?? [])) {
      if (p.team && p.team.trim()) set.add(p.team.trim())
    }
    return Array.from(set).filter((name) =>
      !search.trim() || name.toLowerCase().includes(search.trim().toLowerCase())
    ).sort((a, b) => a.localeCompare(b, 'ja'))
  }, [players, search])

  const wrapperCls = mode === 'initial'
    ? `min-h-screen flex items-center justify-center ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`
    : `fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4`

  const panelCls = `rounded-lg p-6 w-96 max-h-[80vh] flex flex-col ${isLight ? 'bg-white shadow-lg border border-gray-200' : 'bg-gray-800'}`

  if (stage.kind === 'player') {
    return (
      <div className={wrapperCls}>
        <div className={panelCls}>
          <div className="text-center mb-4">
            <div className={`text-xl font-bold mb-1 ${isLight ? 'text-gray-900' : 'text-white'}`}>どの選手としてログインしますか？</div>
            <div className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>あなたが関与した試合のみが表示されます</div>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="選手名で検索"
            className={`w-full mb-3 px-3 py-2 rounded text-sm border ${
              isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-700 border-gray-600 text-white'
            }`}
          />
          <div className="flex-1 overflow-y-auto space-y-1">
            {loadErr && <p className="text-red-400 text-xs">{loadErr}</p>}
            {!loadErr && players === null && <p className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>読み込み中...</p>}
            {players !== null && filteredPlayers.length === 0 && (
              <p className={`text-xs text-center py-4 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
                {players.length === 0 ? '登録選手がいません' : '該当する選手が見つかりません'}
              </p>
            )}
            {filteredPlayers.map((p) => (
              <button
                key={p.id}
                onClick={() => onSelect('player', p.id, null)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  isLight
                    ? 'bg-gray-100 hover:bg-blue-600 text-gray-800 hover:text-white'
                    : 'bg-gray-700 hover:bg-blue-700 text-white'
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between mt-3">
            <button
              onClick={() => mode === 'initial' ? setStage({ kind: 'roles' }) : onCancel?.()}
              className={`text-xs underline ${isLight ? 'text-gray-500' : 'text-gray-400'}`}
            >
              {mode === 'initial' ? '← ロール選択に戻る' : 'キャンセル'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (stage.kind === 'team') {
    return (
      <div className={wrapperCls}>
        <div className={panelCls}>
          <div className="text-center mb-4">
            <div className={`text-xl font-bold mb-1 ${isLight ? 'text-gray-900' : 'text-white'}`}>どのチームのコーチですか？</div>
            <div className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>チーム所属選手の試合のみが表示されます</div>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="チーム名で検索 / 直接入力"
            className={`w-full mb-3 px-3 py-2 rounded text-sm border ${
              isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-700 border-gray-600 text-white'
            }`}
          />
          <div className="flex-1 overflow-y-auto space-y-1">
            {loadErr && <p className="text-red-400 text-xs">{loadErr}</p>}
            {!loadErr && players === null && <p className={`text-xs ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>読み込み中...</p>}
            {players !== null && teams.length === 0 && !search.trim() && (
              <p className={`text-xs text-center py-4 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
                登録チームがありません
              </p>
            )}
            {teams.map((name) => (
              <button
                key={name}
                onClick={() => onSelect('coach', null, name)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  isLight
                    ? 'bg-gray-100 hover:bg-blue-600 text-gray-800 hover:text-white'
                    : 'bg-gray-700 hover:bg-blue-700 text-white'
                }`}
              >
                {name}
              </button>
            ))}
            {search.trim() && !teams.includes(search.trim()) && (
              <button
                onClick={() => onSelect('coach', null, search.trim())}
                className={`w-full text-left px-3 py-2 rounded text-sm border border-dashed ${
                  isLight ? 'border-gray-400 text-gray-700 hover:bg-blue-50' : 'border-gray-500 text-gray-300 hover:bg-gray-700'
                }`}
              >
                + 新規チーム「{search.trim()}」として登録
              </button>
            )}
          </div>
          <div className="flex items-center justify-between mt-3">
            <button
              onClick={() => mode === 'initial' ? setStage({ kind: 'roles' }) : onCancel?.()}
              className={`text-xs underline ${isLight ? 'text-gray-500' : 'text-gray-400'}`}
            >
              {mode === 'initial' ? '← ロール選択に戻る' : 'キャンセル'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // roles ステージ
  return (
    <div className={wrapperCls}>
      <div className={`rounded-lg p-8 w-80 ${isLight ? 'bg-white shadow-lg border border-gray-200' : 'bg-gray-800'}`}>
        <div className="text-center mb-6">
          <div className={`text-3xl font-bold mb-1 ${isLight ? 'text-gray-900' : 'text-white'}`}>ShuttleScope</div>
          <div className={`text-sm ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>ロールを選択してください</div>
        </div>
        <div className="flex flex-col gap-3">
          {(['analyst', 'coach', 'player'] as UserRole[]).map((r) => (
            <button
              key={r}
              onClick={() => {
                if (r === 'player') setStage({ kind: 'player' })
                else if (r === 'coach') setStage({ kind: 'team' })
                else onSelect(r, null, null)
              }}
              className={`py-3 px-4 rounded text-sm font-medium transition-colors ${
                isLight
                  ? 'bg-gray-100 hover:bg-blue-600 text-gray-800 hover:text-white'
                  : 'bg-gray-700 hover:bg-blue-700 text-white'
              }`}
            >
              {t(`roles.${r}`)}
            </button>
          ))}
        </div>
        {mode === 'modal' && onCancel && (
          <button
            onClick={onCancel}
            className={`mt-4 w-full text-xs underline ${isLight ? 'text-gray-500' : 'text-gray-400'}`}
          >
            キャンセル
          </button>
        )}
        <p className={`text-xs mt-4 text-center ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
          POCフェーズ: ロールはブラウザに保存されます
        </p>
      </div>
    </div>
  )
}
