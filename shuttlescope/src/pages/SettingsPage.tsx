import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Edit2, Trash2, CheckCircle, AlertCircle, Play, Cpu, Zap, ToggleLeft, ToggleRight } from 'lucide-react'
import { apiGet, apiPost, apiPut, apiDelete } from '@/api/client'
import { Player, UserRole } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useSettings } from '@/hooks/useSettings'

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
  const [activeTab, setActiveTab] = useState<'players' | 'review' | 'tracknet' | 'account'>('players')
  const { settings, updateSettings, loading: settingsLoading } = useSettings()
  const navigate = useNavigate()

  // 選手一覧取得
  const { data: playersData } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
  })

  // V4-U-003: 要レビュー選手取得
  const { data: reviewPlayersData } = useQuery({
    queryKey: ['players-needs-review'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players/needs_review'),
    enabled: activeTab === 'review',
  })

  // TrackNetモデルステータス取得
  const { data: tracknetStatus } = useQuery({
    queryKey: ['tracknet-status'],
    queryFn: () => apiGet<{ success: boolean; data: { available: boolean; backend: string | null; loaded: boolean } }>('/tracknet/status'),
    enabled: activeTab === 'tracknet',
    refetchInterval: activeTab === 'tracknet' ? 5000 : false,
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

  // V4-U-003: 選手を「確認済み」にする
  const markVerified = useMutation({
    mutationFn: (id: number) =>
      apiPut(`/players/${id}`, { profile_status: 'verified', needs_review: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['players'] })
      queryClient.invalidateQueries({ queryKey: ['players-needs-review'] })
    },
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
      dominant_hand: (player.dominant_hand === 'R' || player.dominant_hand === 'L') ? player.dominant_hand : 'R',
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
        {([
          { key: 'players', label: '選手管理' },
          { key: 'review', label: t('review.title'), badge: reviewPlayersData?.data?.length ?? 0 },
          { key: 'tracknet', label: t('tracknet.tab_label') },
          { key: 'account', label: 'アカウント設定' },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as any)}
            className={`flex items-center gap-1.5 px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}
          >
            {tab.label}
            {'badge' in tab && tab.badge > 0 && (
              <span className="inline-flex items-center justify-center w-4 h-4 text-[10px] bg-orange-500 text-white rounded-full">
                {tab.badge}
              </span>
            )}
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
                    <td className="py-2 pr-4 text-gray-300">
                      {p.dominant_hand === 'R' ? '右' : p.dominant_hand === 'L' ? '左' : '-'}
                    </td>
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

        {/* 要レビュータブ（V4-U-003） */}
        {activeTab === 'review' && (
          <div>
            <h2 className="text-lg font-medium mb-4">{t('review.title')}</h2>
            <div className="mb-6">
              <h3 className="text-sm font-medium text-gray-300 mb-2 flex items-center gap-2">
                <AlertCircle size={14} className="text-orange-400" />
                {t('review.provisional_players')}
              </h3>
              {!reviewPlayersData?.data?.length ? (
                <div className="text-sm text-gray-500 py-4">{t('review.no_items')}</div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-400 border-b border-gray-700">
                      <th className="text-left py-2 pr-4">名前</th>
                      <th className="text-left py-2 pr-4">{t('review.profile_status')}</th>
                      <th className="text-left py-2 pr-4">利き手</th>
                      <th className="text-left py-2 pr-4">試合数</th>
                      <th className="text-left py-2">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reviewPlayersData.data.map((p) => (
                      <tr key={p.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                        <td className="py-2 pr-4">
                          <div className="flex items-center gap-2">
                            {p.name}
                            {p.profile_status === 'provisional' && (
                              <span className="text-xs text-yellow-400 bg-yellow-400/10 px-1 rounded">暫定</span>
                            )}
                          </div>
                        </td>
                        <td className="py-2 pr-4 text-gray-300">
                          {t(`player.profile_status_${p.profile_status ?? 'provisional'}`)}
                        </td>
                        <td className="py-2 pr-4 text-gray-300">
                          {p.dominant_hand === 'R' ? '右' : p.dominant_hand === 'L' ? '左' : t('player.unknown_hand')}
                        </td>
                        <td className="py-2 pr-4 text-gray-300">{p.match_count ?? 0}</td>
                        <td className="py-2">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => openEdit(p)}
                              className="p-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
                              title="編集"
                            >
                              <Edit2 size={12} />
                            </button>
                            <button
                              onClick={() => markVerified.mutate(p.id)}
                              disabled={markVerified.isPending}
                              className="p-1.5 rounded bg-green-800 hover:bg-green-700 text-green-300"
                              title={t('review.mark_verified')}
                            >
                              <CheckCircle size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* TrackNet設定タブ */}
        {activeTab === 'tracknet' && (
          <div className="max-w-xl space-y-6">
            <h2 className="text-lg font-medium">{t('tracknet.tab_label')}</h2>

            {/* モデルステータス */}
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Zap size={14} className="text-yellow-400" />
                {t('tracknet.model_status')}
              </h3>
              {!tracknetStatus ? (
                <p className="text-sm text-gray-500">{t('tracknet.backend_offline')}</p>
              ) : tracknetStatus.data?.available ? (
                <div className="flex items-center gap-2">
                  <CheckCircle size={14} className="text-green-400" />
                  <span className="text-sm text-green-300">
                    {t('tracknet.model_ready')} — {tracknetStatus.data.backend}
                  </span>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <AlertCircle size={14} className="text-orange-400" />
                    <span className="text-sm text-orange-300">{t('tracknet.model_not_found')}</span>
                  </div>
                  <div className="bg-gray-900 rounded p-3 text-xs text-gray-400 font-mono space-y-1">
                    <p className="text-gray-300 font-sans font-medium text-xs mb-1">{t('tracknet.setup_instructions')}</p>
                    <p>python -m backend.tracknet.setup download</p>
                    <p>python -m backend.tracknet.setup export</p>
                    <p>python -m backend.tracknet.setup convert</p>
                    <p className="text-gray-500 font-sans"># または一括: python -m backend.tracknet.setup all</p>
                  </div>
                </div>
              )}
            </div>

            {/* 有効/無効トグル */}
            <div className="flex items-center justify-between bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div>
                <p className="text-sm font-medium">{t('tracknet.enable_toggle')}</p>
                <p className="text-xs text-gray-400 mt-0.5">{t('tracknet.enable_description')}</p>
              </div>
              <button
                onClick={() => updateSettings({ tracknet_enabled: !settings.tracknet_enabled })}
                disabled={settingsLoading}
                className="flex-shrink-0"
              >
                {settings.tracknet_enabled
                  ? <ToggleRight size={32} className="text-blue-400" />
                  : <ToggleLeft size={32} className="text-gray-500" />}
              </button>
            </div>

            {/* バックエンド選択 */}
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <h3 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                <Cpu size={14} />
                {t('tracknet.backend_label')}
              </h3>
              <div className="flex gap-2">
                {([
                  { value: 'openvino', label: 'OpenVINO (Intel GPU / CPU)' },
                  { value: 'onnx_cpu', label: 'ONNX CPU' },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => updateSettings({ tracknet_backend: opt.value })}
                    className={`flex-1 py-2 px-3 rounded text-sm border transition-colors ${
                      settings.tracknet_backend === opt.value
                        ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                        : 'border-gray-600 bg-gray-700 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 解析モード */}
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <h3 className="text-sm font-medium text-gray-300 mb-1">{t('tracknet.mode_label')}</h3>
              <p className="text-xs text-gray-500 mb-3">{t('tracknet.mode_description')}</p>
              <div className="flex gap-2">
                {([
                  { value: 'batch', label: t('tracknet.mode_batch') },
                  { value: 'assist', label: t('tracknet.mode_assist') },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => updateSettings({ tracknet_mode: opt.value })}
                    className={`flex-1 py-2 px-3 rounded text-sm border transition-colors ${
                      settings.tracknet_mode === opt.value
                        ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                        : 'border-gray-600 bg-gray-700 text-gray-300 hover:border-gray-500'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* CPU使用率上限 */}
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-gray-300">{t('tracknet.cpu_limit_label')}</h3>
                <span className="text-sm font-mono text-blue-300">{settings.tracknet_max_cpu_pct}%</span>
              </div>
              <input
                type="range"
                min={10}
                max={90}
                step={5}
                value={settings.tracknet_max_cpu_pct}
                onChange={(e) => updateSettings({ tracknet_max_cpu_pct: Number(e.target.value) })}
                className="w-full accent-blue-500"
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>10%</span>
                <span>90%</span>
              </div>
            </div>
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
