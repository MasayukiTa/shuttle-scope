import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Pencil, Plus, Trash2, X, Check } from 'lucide-react'

import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useIsLightMode } from '@/hooks/useIsLightMode'

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

interface FormState {
  role: string
  display_name: string
  username: string
  credential: string
  player_id: string
  team_name: string
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

const emptyForm = (): FormState => ({
  role: 'player',
  display_name: '',
  username: '',
  credential: '',
  player_id: '',
  team_name: '',
})

function SecretField(props: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  autoComplete?: string
  inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode']
  hint?: string
  isLight: boolean
  textMuted: string
  inputCls: string
}) {
  const [visible, setVisible] = useState(false)

  return (
    <div>
      <label className={`block text-xs font-medium mb-1 ${props.textMuted}`}>{props.label}</label>
      <div className="relative">
        <input
          type={visible ? 'text' : 'password'}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          className={`${props.inputCls} pr-11`}
          placeholder={props.placeholder}
          autoComplete={props.autoComplete}
          inputMode={props.inputMode}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className={`absolute inset-y-0 right-0 flex items-center px-3 ${
            props.isLight ? 'text-gray-500 hover:text-gray-700' : 'text-gray-400 hover:text-gray-200'
          }`}
          title={visible ? '非表示' : '表示'}
          aria-label={visible ? 'パスワードを隠す' : 'パスワードを表示'}
        >
          {visible ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
      {props.hint ? <p className={`mt-1 text-xs ${props.textMuted}`}>{props.hint}</p> : null}
    </div>
  )
}

export function UserManagementPage() {
  type SortKey = 'display_name' | 'username' | 'player_name'

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
  const [searchTerm, setSearchTerm] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('display_name')

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const border = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMain = isLight ? 'text-gray-900' : 'text-gray-100'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowHover = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/50'
  const inputCls = `w-full border ${isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-700'} rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${textMain}`

  const isPlayerRole = form.role === 'player'
  const isCoachRole = form.role === 'coach'

  const credentialLabel = useMemo(() => {
    if (isPlayerRole) {
      return editId != null ? 'パスワード / PIN を更新' : 'パスワード / PIN'
    }
    return editId != null ? 'パスワードを更新' : 'パスワード'
  }, [editId, isPlayerRole])

  const filteredUsers = useMemo(() => {
    const keyword = searchTerm.trim().toLowerCase()

    const filtered = keyword
      ? users.filter((user) => {
          const values = [user.display_name, user.username, user.player_name]
          return values.some((value) => (value ?? '').toLowerCase().includes(keyword))
        })
      : users

    return [...filtered].sort((a, b) => {
      const aValue = (a[sortKey] ?? '').toString().toLowerCase()
      const bValue = (b[sortKey] ?? '').toString().toLowerCase()
      return aValue.localeCompare(bValue, 'ja')
    })
  }, [searchTerm, sortKey, users])

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

  useEffect(() => {
    load()
  }, [])

  const canCreate = myRole === 'admin' || myRole === 'analyst'
  const canDelete = myRole === 'admin'
  const isSelfOnly = myRole === 'player'

  if (!myRole || myRole === '') {
    return <div className="p-8 text-center text-gray-500">ユーザー管理の権限がありません</div>
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
      credential: '',
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
    if (!form.username.trim()) {
      setError('ログインIDを入力してください')
      return
    }

    setSaving(true)
    setError(null)

    try {
      if (editId != null) {
        const body: Record<string, unknown> = {
          display_name: form.display_name || undefined,
        }
        if (!isSelfOnly) {
          body.username = form.username.trim()
          body.team_name = form.team_name || undefined
          body.player_id = form.player_id ? parseInt(form.player_id, 10) : undefined
        }
        if (form.credential.trim()) body.password = form.credential.trim()
        await apiPut(`/auth/users/${editId}`, body)
      } else {
        const body: Record<string, unknown> = {
          role: form.role,
          display_name: form.display_name.trim(),
          username: form.username.trim(),
          team_name: form.team_name.trim() || undefined,
          player_id: form.player_id ? parseInt(form.player_id, 10) : undefined,
        }
        if (form.credential.trim()) body.password = form.credential.trim()
        await apiPost('/auth/users', body)
      }
      setShowForm(false)
      await load()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (u: UserRow) => {
    const targetName = u.display_name ?? u.username
    if (!window.confirm(`${targetName} を削除しますか？`)) return
    try {
      await apiDelete(`/auth/users/${u.id}`)
      await load()
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className={`shrink-0 px-6 py-4 border-b ${border} ${panelBg} flex items-center justify-between`}>
        <div>
          <h1 className={`text-base font-semibold ${textMain}`}>ユーザー管理</h1>
          {isSelfOnly && (
            <p className={`text-xs mt-0.5 ${textMuted}`}>自分のプロフィールを編集できます</p>
          )}
          {myRole === 'coach' && (
            <p className={`text-xs mt-0.5 ${textMuted}`}>チームメンバーのみ表示・編集できます</p>
          )}
        </div>
        {canCreate && (
          <button
            onClick={openCreate}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-3 py-1.5 rounded-lg"
          >
            <Plus size={14} />
            ユーザー追加
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {error ? (
          <div className="mb-4 bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-4 py-2">
            {error}
          </div>
        ) : null}

        <div className={`mb-4 ${panelBg} border ${border} rounded-xl p-4`}>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
            <div>
              <label className={`block text-xs font-medium mb-1 ${textMuted}`}>検索</label>
              <input
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className={inputCls}
                placeholder="表示名・ログインID・選手名で検索"
              />
            </div>
            <div>
              <label className={`block text-xs font-medium mb-1 ${textMuted}`}>並び順</label>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className={inputCls}
              >
                <option value="display_name">表示名順</option>
                <option value="username">ログインID順</option>
                <option value="player_name">選手名順</option>
              </select>
            </div>
          </div>
        </div>

        {showForm ? (
          <div className={`mb-6 ${panelBg} border ${border} rounded-xl p-5`}>
            <div className="flex items-center justify-between mb-4">
              <h2 className={`text-sm font-semibold ${textMain}`}>
                {editId != null ? 'ユーザー編集' : '新規ユーザー追加'}
              </h2>
              <button onClick={() => setShowForm(false)} className={textMuted}>
                <X size={16} />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {editId == null && canCreate ? (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>ロール</label>
                  <select
                    value={form.role}
                    onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                    className={inputCls}
                  >
                    {['admin', 'analyst', 'coach', 'player'].map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              <div>
                <label className={`block text-xs font-medium mb-1 ${textMuted}`}>表示名 *</label>
                <input
                  value={form.display_name}
                  onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                  className={inputCls}
                  placeholder="山田 太郎"
                />
              </div>

              {!isSelfOnly && (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>ログインID *</label>
                  <input
                    value={form.username}
                    onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                    className={inputCls}
                    placeholder="admin001"
                    disabled={isSelfOnly}
                  />
                  <p className={`mt-1 text-xs ${textMuted}`}>
                    6文字以上20文字未満。英数字、`-`、`_` が使えます。
                  </p>
                </div>
              )}

              <SecretField
                label={credentialLabel}
                value={form.credential}
                onChange={(value) => setForm((f) => ({ ...f, credential: value }))}
                placeholder={isPlayerRole ? '例: 2468 または strong-pass' : '新しいパスワード'}
                autoComplete="new-password"
                inputMode={isPlayerRole ? 'text' : undefined}
                hint={
                  editId != null
                    ? '空欄なら変更しません'
                    : isPlayerRole
                      ? '選手も通常のパスワードとして設定できます'
                      : undefined
                }
                isLight={isLight}
                textMuted={textMuted}
                inputCls={inputCls}
              />

              {isCoachRole ? (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>チーム名</label>
                  <input
                    value={form.team_name}
                    onChange={(e) => setForm((f) => ({ ...f, team_name: e.target.value }))}
                    className={inputCls}
                    placeholder="ACT SAIKYO"
                  />
                </div>
              ) : null}

              {isPlayerRole ? (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>選手紐付け</label>
                  <select
                    value={form.player_id}
                    onChange={(e) => setForm((f) => ({ ...f, player_id: e.target.value }))}
                    className={inputCls}
                  >
                    <option value="">未選択</option>
                    {players.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
            </div>

            <div className="mt-4 flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded-lg"
              >
                <Check size={14} />
                {saving ? '保存中...' : '保存'}
              </button>
              <button
                onClick={() => setShowForm(false)}
                className={`text-sm px-4 py-1.5 rounded-lg border ${border} ${textMuted}`}
              >
                キャンセル
              </button>
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className={`text-sm ${textMuted}`}>読み込み中...</div>
        ) : (
          <div className={`${panelBg} border ${border} rounded-xl overflow-hidden`}>
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b ${border} text-left`}>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted}`}>ロール</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted}`}>表示名</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted} hidden sm:table-cell`}>
                    ログインID / チーム / 選手
                  </th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted} hidden sm:table-cell`}>認証</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((u) => (
                  <tr key={u.id} className={`border-b last:border-0 ${border} ${rowHover}`}>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${ROLE_COLORS[u.role] ?? 'bg-gray-100 text-gray-600'}`}>
                        {ROLE_LABELS[u.role] ?? u.role}
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-medium ${textMain}`}>{u.display_name ?? '—'}</td>
                    <td className={`px-4 py-2.5 ${textMuted} text-xs hidden sm:table-cell`}>
                      <div>{u.username || '—'}</div>
                      {u.role === 'coach' ? <div>Team: {u.team_name || '—'}</div> : null}
                      {u.role === 'player' ? <div>Player: {u.player_name || '—'}</div> : null}
                    </td>
                    <td className={`px-4 py-2.5 text-xs ${textMuted} hidden sm:table-cell`}>
                      {u.has_credential ? '設定済み' : '未設定'}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2 justify-end">
                        <button onClick={() => openEdit(u)} className={`${textMuted} hover:text-blue-500`}>
                          <Pencil size={14} />
                        </button>
                        {canDelete && (
                          <button onClick={() => handleDelete(u)} className={`${textMuted} hover:text-red-500`}>
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={5} className={`px-4 py-8 text-center ${textMuted} text-sm`}>
                      {searchTerm.trim() ? '該当するユーザーが見つかりません' : 'ユーザーが登録されていません'}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
