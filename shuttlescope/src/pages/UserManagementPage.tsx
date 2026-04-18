import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import { apiGet, apiPost, apiPut, apiDelete } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { Pencil, Trash2, Plus, X, Check } from 'lucide-react'

interface UserRow {
  id: number
  username: string
  role: string
  display_name: string | null
  team_name: string | null
  player_id: number | null
  player_name: string | null
  has_credential: boolean
  created_at: string | null
}

interface PlayerOption {
  id: number
  name: string
}

const ROLE_LABELS: Record<string, string> = {
  admin: '管理者',
  analyst: 'アナリスト',
  coach: 'コーチ',
  player: '選手',
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'bg-red-100 text-red-700',
  analyst: 'bg-purple-100 text-purple-700',
  coach: 'bg-blue-100 text-blue-700',
  player: 'bg-green-100 text-green-700',
}

interface FormState {
  role: string
  display_name: string
  username: string
  password: string
  pin: string
  player_id: string
  team_name: string
}

const emptyForm = (): FormState => ({
  role: 'player',
  display_name: '',
  username: '',
  password: '',
  pin: '',
  player_id: '',
  team_name: '',
})

export function UserManagementPage() {
  const { t } = useTranslation()
  const { role: myRole } = useAuth()
  const isLight = useIsLightMode()
  const [users, setUsers] = useState<UserRow[]>([])
  const [players, setPlayers] = useState<PlayerOption[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const border = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMain = isLight ? 'text-gray-900' : 'text-gray-100'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowHover = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/50'

  const load = async () => {
    setLoading(true)
    try {
      const [ur, pr] = await Promise.all([
        apiGet<{ success: boolean; data: UserRow[] }>('/auth/users'),
        apiGet<{ success: boolean; data: { id: number; name: string }[] }>('/players?limit=500'),
      ])
      setUsers(ur.data ?? [])
      setPlayers(pr.data ?? [])
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  if (myRole !== 'admin' && myRole !== 'analyst') {
    return (
      <div className="p-8 text-center text-gray-500">管理者権限が必要です</div>
    )
  }

  const openCreate = () => {
    setForm(emptyForm())
    setEditId(null)
    setError(null)
    setShowForm(true)
  }

  const openEdit = (u: UserRow) => {
    setForm({
      role: u.role,
      display_name: u.display_name ?? '',
      username: u.username ?? '',
      password: '',
      pin: '',
      player_id: u.player_id ? String(u.player_id) : '',
      team_name: u.team_name ?? '',
    })
    setEditId(u.id)
    setError(null)
    setShowForm(true)
  }

  const handleSave = async () => {
    if (!form.display_name.trim()) {
      setError('表示名を入力してください')
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (editId != null) {
        const body: Record<string, unknown> = {
          display_name: form.display_name || undefined,
          team_name: form.team_name || undefined,
          player_id: form.player_id ? parseInt(form.player_id) : undefined,
        }
        if (form.password) body.password = form.password
        if (form.pin) body.pin = form.pin
        await apiPut(`/auth/users/${editId}`, body)
      } else {
        const body: Record<string, unknown> = {
          role: form.role,
          display_name: form.display_name,
          username: form.username || undefined,
          team_name: form.team_name || undefined,
          player_id: form.player_id ? parseInt(form.player_id) : undefined,
        }
        if (form.password) body.password = form.password
        if (form.pin) body.pin = form.pin
        await apiPost('/auth/users', body)
      }
      setShowForm(false)
      await load()
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (u: UserRow) => {
    if (!window.confirm(`「${u.display_name ?? u.username}」を削除しますか？`)) return
    try {
      await apiDelete(`/auth/users/${u.id}`)
      await load()
    } catch (e) {
      setError(String(e))
    }
  }

  // t() を参照することで未使用変数警告を抑制
  void t

  const inputCls = `w-full border ${isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-700'} rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${textMain}`

  return (
    <div className="flex flex-col h-full">
      {/* ヘッダ */}
      <div className={`shrink-0 px-6 py-4 border-b ${border} ${panelBg} flex items-center justify-between`}>
        <h1 className={`text-base font-semibold ${textMain}`}>ユーザ管理</h1>
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-3 py-1.5 rounded-lg"
        >
          <Plus size={14} />
          ユーザ追加
        </button>
      </div>

      {/* コンテンツ */}
      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-4 py-2">
            {error}
          </div>
        )}

        {/* 追加/編集フォーム */}
        {showForm && (
          <div className={`mb-6 ${panelBg} border ${border} rounded-xl p-5`}>
            <div className="flex items-center justify-between mb-4">
              <h2 className={`text-sm font-semibold ${textMain}`}>
                {editId != null ? 'ユーザ編集' : '新規ユーザ追加'}
              </h2>
              <button onClick={() => setShowForm(false)} className={textMuted}><X size={16} /></button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {editId == null && (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>ロール</label>
                  <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))} className={inputCls}>
                    {['admin', 'analyst', 'coach', 'player'].map(r => (
                      <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className={`block text-xs font-medium mb-1 ${textMuted}`}>表示名 *</label>
                <input value={form.display_name} onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} className={inputCls} placeholder="山田コーチ" />
              </div>
              {(editId == null && (form.role === 'admin' || form.role === 'analyst')) && (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>ユーザ名</label>
                  <input value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))} className={inputCls} placeholder="yamada" />
                </div>
              )}
              {(form.role === 'admin' || form.role === 'analyst') && (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{editId != null ? 'パスワード変更（空欄=変更なし）' : 'パスワード'}</label>
                  <input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} className={inputCls} autoComplete="new-password" />
                </div>
              )}
              {form.role === 'coach' && (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>チーム名</label>
                  <input value={form.team_name} onChange={e => setForm(f => ({ ...f, team_name: e.target.value }))} className={inputCls} placeholder="ACT SAIKYO" />
                </div>
              )}
              {form.role === 'player' && (
                <>
                  <div>
                    <label className={`block text-xs font-medium mb-1 ${textMuted}`}>選手連携</label>
                    <select value={form.player_id} onChange={e => setForm(f => ({ ...f, player_id: e.target.value }))} className={inputCls}>
                      <option value="">（未連携）</option>
                      {players.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{editId != null ? 'PIN変更（空欄=変更なし）' : 'PIN（任意）'}</label>
                    <input type="password" value={form.pin} onChange={e => setForm(f => ({ ...f, pin: e.target.value }))} className={inputCls} placeholder="••••" inputMode="numeric" autoComplete="new-password" />
                  </div>
                </>
              )}
            </div>
            {error && <div className="mt-2 text-red-500 text-xs">{error}</div>}
            <div className="mt-4 flex gap-2">
              <button onClick={handleSave} disabled={saving} className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded-lg">
                <Check size={14} />
                {saving ? '保存中...' : '保存'}
              </button>
              <button onClick={() => setShowForm(false)} className={`text-sm px-4 py-1.5 rounded-lg border ${border} ${textMuted}`}>
                キャンセル
              </button>
            </div>
          </div>
        )}

        {/* ユーザ一覧テーブル */}
        {loading ? (
          <div className={`text-sm ${textMuted}`}>読み込み中...</div>
        ) : (
          <div className={`${panelBg} border ${border} rounded-xl overflow-hidden`}>
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b ${border} text-left`}>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted}`}>ロール</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted}`}>表示名</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted} hidden sm:table-cell`}>ユーザ名/チーム/選手</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted} hidden sm:table-cell`}>認証</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id} className={`border-b last:border-0 ${border} ${rowHover}`}>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${ROLE_COLORS[u.role] ?? 'bg-gray-100 text-gray-600'}`}>
                        {ROLE_LABELS[u.role] ?? u.role}
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-medium ${textMain}`}>{u.display_name ?? '—'}</td>
                    <td className={`px-4 py-2.5 ${textMuted} text-xs hidden sm:table-cell`}>
                      {u.role === 'coach' && u.team_name}
                      {u.role === 'player' && u.player_name}
                      {(u.role === 'admin' || u.role === 'analyst') && u.username}
                    </td>
                    <td className={`px-4 py-2.5 text-xs ${textMuted} hidden sm:table-cell`}>
                      {u.has_credential ? '✓' : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2 justify-end">
                        <button onClick={() => openEdit(u)} className={`${textMuted} hover:text-blue-500`}><Pencil size={14} /></button>
                        <button onClick={() => handleDelete(u)} className={`${textMuted} hover:text-red-500`}><Trash2 size={14} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr><td colSpan={5} className={`px-4 py-8 text-center ${textMuted} text-sm`}>ユーザが登録されていません</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
