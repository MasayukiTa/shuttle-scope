import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Edit2, Trash2, CheckCircle } from 'lucide-react'
import { apiGet, apiPost, apiPut, apiDelete } from '@/api/client'
import { Player, UserRole } from '@/types'
import { useAuth } from '@/hooks/useAuth'

interface PlayerFormData {
  name: string
  name_en: string
  team: string
  nationality: string
  dominant_hand: 'R' | 'L'
  birth_year: string
  world_ranking: string
  is_target: boolean
  notes: string
}

const defaultPlayerForm = (): PlayerFormData => ({
  name: '',
  name_en: '',
  team: '',
  nationality: '',
  dominant_hand: 'R',
  birth_year: '',
  world_ranking: '',
  is_target: false,
  notes: '',
})

export function SettingsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { role, setRole } = useAuth()

  const [showPlayerForm, setShowPlayerForm] = useState(false)
  const [editingPlayer, setEditingPlayer] = useState<Player | null>(null)
  const [playerForm, setPlayerForm] = useState<PlayerFormData>(defaultPlayerForm())
  const [activeTab, setActiveTab] = useState<'players' | 'account'>('players')

  // 選手一覧取得
  const { data: playersData } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })

  // 選手作成
  const createPlayer = useMutation({
    mutationFn: (body: any) => apiPost('/players', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['players'] })
      setShowPlayerForm(false)
      setPlayerForm(defaultPlayerForm())
    },
  })

  // 選手更新
  const updatePlayer = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => apiPut(`/players/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['players'] })
      setShowPlayerForm(false)
      setEditingPlayer(null)
      setPlayerForm(defaultPlayerForm())
    },
  })

  // 選手削除
  const deletePlayer = useMutation({
    mutationFn: (id: number) => apiDelete(`/players/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['players'] }),
  })

  const handlePlayerSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const body = {
      name: playerForm.name,
      name_en: playerForm.name_en || undefined,
      team: playerForm.team || undefined,
      nationality: playerForm.nationality || undefined,
      dominant_hand: playerForm.dominant_hand,
      birth_year: playerForm.birth_year ? Number(playerForm.birth_year) : undefined,
      world_ranking: playerForm.world_ranking ? Number(playerForm.world_ranking) : undefined,
      is_target: playerForm.is_target,
      notes: playerForm.notes || undefined,
    }

    if (editingPlayer) {
      updatePlayer.mutate({ id: editingPlayer.id, body })
    } else {
      createPlayer.mutate(body)
    }
  }

  const openEdit = (player: Player) => {
    setEditingPlayer(player)
    setPlayerForm({
      name: player.name,
      name_en: player.name_en ?? '',
      team: player.team ?? '',
      nationality: player.nationality ?? '',
      dominant_hand: player.dominant_hand,
      birth_year: player.birth_year ? String(player.birth_year) : '',
      world_ranking: player.world_ranking ? String(player.world_ranking) : '',
      is_target: player.is_target,
      notes: player.notes ?? '',
    })
    setShowPlayerForm(true)
  }

  const players = playersData?.data ?? []

  return (
    <div className="flex flex-col h-full bg-gray-900 text-white">
      {/* ヘッダー */}
      <div className="px-6 py-4 border-b border-gray-700">
        <h1 className="text-xl font-semibold">{t('nav.settings')}</h1>
      </div>

      {/* タブ */}
      <div className="flex border-b border-gray-700">
        {(['players', 'account'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            {tab === 'players' ? '選手管理' : 'アカウント設定'}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {/* 選手管理タブ */}
        {activeTab === 'players' && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-medium">選手一覧</h2>
              <button
                onClick={() => { setEditingPlayer(null); setPlayerForm(defaultPlayerForm()); setShowPlayerForm(true) }}
                className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 rounded text-sm"
              >
                <Plus size={14} />
                選手追加
              </button>
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-700">
                  <th className="text-left py-2 pr-4">名前</th>
                  <th className="text-left py-2 pr-4">チーム</th>
                  <th className="text-left py-2 pr-4">国籍</th>
                  <th className="text-left py-2 pr-4">利き手</th>
                  <th className="text-left py-2 pr-4">世界ランク</th>
                  <th className="text-left py-2 pr-4">解析対象</th>
                  <th className="text-left py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {players.map((p) => (
                  <tr key={p.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="py-2 pr-4">
                      <div>{p.name}</div>
                      {p.name_en && <div className="text-xs text-gray-500">{p.name_en}</div>}
                    </td>
                    <td className="py-2 pr-4 text-gray-300">{p.team ?? '-'}</td>
                    <td className="py-2 pr-4 text-gray-300">{p.nationality ?? '-'}</td>
                    <td className="py-2 pr-4 text-gray-300">{p.dominant_hand === 'R' ? '右' : '左'}</td>
                    <td className="py-2 pr-4 text-gray-300">{p.world_ranking ? `#${p.world_ranking}` : '-'}</td>
                    <td className="py-2 pr-4">
                      {p.is_target && <CheckCircle size={14} className="text-green-400" />}
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => openEdit(p)}
                          className="p-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                        >
                          <Edit2 size={12} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`「${p.name}」を削除しますか？`)) deletePlayer.mutate(p.id)
                          }}
                          className="p-1.5 rounded bg-red-900/50 hover:bg-red-700 text-red-400"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {players.length === 0 && (
              <div className="text-center text-gray-500 py-8">
                選手が登録されていません。「選手追加」ボタンで追加してください。
              </div>
            )}
          </div>
        )}

        {/* アカウント設定タブ */}
        {activeTab === 'account' && (
          <div className="max-w-md">
            <h2 className="text-lg font-medium mb-4">ロール設定（POCフェーズ）</h2>
            <div className="flex flex-col gap-2">
              {(['analyst', 'coach', 'player'] as UserRole[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setRole(r)}
                  className={`flex items-center justify-between px-4 py-3 rounded border ${
                    role === r
                      ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                      : 'border-gray-600 bg-gray-800 text-gray-300 hover:border-gray-500'
                  }`}
                >
                  <span className="font-medium">{t(`roles.${r}`)}</span>
                  {role === r && <CheckCircle size={16} className="text-blue-400" />}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-500 mt-4">
              ※ POCフェーズでは簡易ロール管理（ローカルストレージ保存）。
              本番展開時にJWT認証へ移行予定。
            </p>
          </div>
        )}
      </div>

      {/* 選手フォームモーダル */}
      {showPlayerForm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg w-full max-w-lg">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
              <h2 className="text-lg font-semibold">{editingPlayer ? '選手編集' : '選手追加'}</h2>
              <button onClick={() => { setShowPlayerForm(false); setEditingPlayer(null) }} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <form onSubmit={handlePlayerSubmit} className="p-6 flex flex-col gap-3">
              <div>
                <label className="block text-sm text-gray-400 mb-1">{t('player.name')} *</label>
                <input
                  value={playerForm.name}
                  onChange={(e) => setPlayerForm({ ...playerForm, name: e.target.value })}
                  required
                  className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  placeholder="例: 山田 太郎"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('player.name_en')}</label>
                  <input
                    value={playerForm.name_en}
                    onChange={(e) => setPlayerForm({ ...playerForm, name_en: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="Yamada Taro"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('player.team')}</label>
                  <input
                    value={playerForm.team}
                    onChange={(e) => setPlayerForm({ ...playerForm, team: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('player.nationality')}</label>
                  <input
                    value={playerForm.nationality}
                    onChange={(e) => setPlayerForm({ ...playerForm, nationality: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="JPN"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('player.dominant_hand')}</label>
                  <select
                    value={playerForm.dominant_hand}
                    onChange={(e) => setPlayerForm({ ...playerForm, dominant_hand: e.target.value as 'R' | 'L' })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                  >
                    <option value="R">右利き</option>
                    <option value="L">左利き</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('player.birth_year')}</label>
                  <input
                    type="number"
                    value={playerForm.birth_year}
                    onChange={(e) => setPlayerForm({ ...playerForm, birth_year: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="2000"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">{t('player.world_ranking')}</label>
                  <input
                    type="number"
                    value={playerForm.world_ranking}
                    onChange={(e) => setPlayerForm({ ...playerForm, world_ranking: e.target.value })}
                    className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                    placeholder="100"
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={playerForm.is_target}
                  onChange={(e) => setPlayerForm({ ...playerForm, is_target: e.target.checked })}
                  className="w-4 h-4"
                />
                <span className="text-sm text-gray-300">{t('player.is_target')}（解析メイン対象）</span>
              </label>
              <div>
                <label className="block text-sm text-gray-400 mb-1">{t('player.notes')}</label>
                <textarea
                  value={playerForm.notes}
                  onChange={(e) => setPlayerForm({ ...playerForm, notes: e.target.value })}
                  rows={2}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-sm"
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={createPlayer.isPending || updatePlayer.isPending}
                  className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium disabled:opacity-50"
                >
                  {(createPlayer.isPending || updatePlayer.isPending) ? '保存中...' : '保存'}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowPlayerForm(false); setEditingPlayer(null) }}
                  className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm"
                >
                  {t('app.cancel')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
