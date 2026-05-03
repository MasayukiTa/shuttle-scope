import { useEffect, useMemo, useState } from 'react'
import { Pencil, Plus, X, Check, Users, Loader2 } from 'lucide-react'

import { listTeams, createTeam, patchTeam, apiGet, type TeamDTO } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useIsMobile } from '@/hooks/useIsMobile'

interface UserBrief {
  id: number
  username: string
  display_name: string | null
  role: string
  team_id: number | null
}

interface FormState {
  name: string
  display_id: string
  short_name: string
  notes: string
}

const emptyForm = (): FormState => ({ name: '', display_id: '', short_name: '', notes: '' })

export function TeamManagementPage() {
  const { role } = useAuth()
  const isAdmin = role === 'admin'
  const isCoach = role === 'coach'
  const [teams, setTeams] = useState<TeamDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<FormState>(emptyForm())
  // メンバー一覧（admin: 全 user / coach: 自チーム）
  const [users, setUsers] = useState<UserBrief[]>([])
  const [expandedTeamId, setExpandedTeamId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [savingId, setSavingId] = useState<number | null>(null)
  const isMobile = useIsMobile()

  const load = async () => {
    setLoading(true)
    try {
      const [tres, ures] = await Promise.all([
        listTeams(),
        apiGet<{ success: boolean; data: UserBrief[] }>('/auth/users').catch(
          () => ({ success: false, data: [] as UserBrief[] }),
        ),
      ])
      setTeams(tres.data || [])
      setUsers(ures.data || [])
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'チーム一覧の取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const usersByTeam = useMemo(() => {
    const map: Record<number, UserBrief[]> = {}
    for (const u of users) {
      if (u.team_id == null) continue
      if (!map[u.team_id]) map[u.team_id] = []
      map[u.team_id].push(u)
    }
    return map
  }, [users])

  useEffect(() => {
    load()
  }, [])

  const handleCreate = async () => {
    if (!form.name.trim()) {
      setError('チーム名を入力してください')
      return
    }
    setCreating(true)
    try {
      await createTeam({
        name: form.name.trim(),
        display_id: form.display_id.trim() || null,
        short_name: form.short_name.trim() || null,
        notes: form.notes.trim() || null,
      })
      setShowCreate(false)
      setForm(emptyForm())
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'チーム作成に失敗しました')
    } finally {
      setCreating(false)
    }
  }

  const startEdit = (t: TeamDTO) => {
    setEditingId(t.id)
    setEditForm({
      name: t.name,
      display_id: t.display_id || '',
      short_name: t.short_name || '',
      notes: t.notes || '',
    })
  }

  const handleSave = async (id: number) => {
    setSavingId(id)
    try {
      await patchTeam(id, {
        name: editForm.name.trim() || undefined,
        display_id: editForm.display_id.trim() || null,
        short_name: editForm.short_name.trim() || null,
        notes: editForm.notes.trim() || null,
      })
      setEditingId(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新に失敗しました')
    } finally {
      setSavingId(null)
    }
  }

  if (!isAdmin && !isCoach) {
    return (
      <div className="p-6">
        <p className="text-sm text-gray-500">このページは admin / coach のみ利用できます。</p>
      </div>
    )
  }

  return (
    <div className="p-3 sm:p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-4 gap-2">
        <h1 className="text-xl font-bold truncate">チーム管理</h1>
        {isAdmin && (
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 shrink-0"
          >
            <Plus size={16} /> <span className="hidden sm:inline">新規作成</span><span className="sm:hidden">追加</span>
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded">
          {error}
        </div>
      )}

      {showCreate && (
        <div className="mb-6 p-4 border rounded bg-gray-50">
          <h2 className="font-semibold mb-3">新規チーム</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1">表示名（必須）</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-3 py-2 border rounded"
                placeholder="例: Resonac"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1">識別子 (display_id)</label>
              <input
                value={form.display_id}
                onChange={(e) => setForm({ ...form, display_id: e.target.value })}
                className="w-full px-3 py-2 border rounded"
                placeholder="任意の一意な文字列（例: RESO-001）"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1">短縮名</label>
              <input
                value={form.short_name}
                onChange={(e) => setForm({ ...form, short_name: e.target.value })}
                className="w-full px-3 py-2 border rounded"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs font-medium mb-1">メモ</label>
              <textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                className="w-full px-3 py-2 border rounded"
                rows={2}
              />
            </div>
          </div>
          <div className="mt-3 flex flex-col-reverse sm:flex-row gap-2 sm:justify-end">
            <button
              onClick={() => {
                setShowCreate(false)
                setForm(emptyForm())
              }}
              disabled={creating}
              className="px-3 py-2 border rounded disabled:opacity-50 w-full sm:w-auto"
            >
              キャンセル
            </button>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-3 py-2 bg-blue-600 text-white rounded disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center justify-center gap-2 w-full sm:w-auto"
            >
              {creating && <Loader2 size={14} className="animate-spin" />}
              {creating ? '作成中…' : '作成'}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">読み込み中…</p>
      ) : isMobile ? (
        <div className="space-y-2">
          {teams.length === 0 && (
            <div className="py-6 text-center text-sm text-gray-500">表示できるチームがありません。</div>
          )}
          {teams.map((t) => {
            const editing = editingId === t.id
            const expanded = expandedTeamId === t.id
            const members = usersByTeam[t.id] || []
            return (
              <div key={t.id} className="border rounded p-3 bg-white">
                {editing ? (
                  <div className="space-y-2">
                    <input
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="w-full px-2 py-1.5 border rounded text-sm"
                      placeholder="表示名"
                    />
                    <input
                      value={editForm.display_id}
                      onChange={(e) => setEditForm({ ...editForm, display_id: e.target.value })}
                      className="w-full px-2 py-1.5 border rounded text-sm"
                      placeholder="識別子"
                    />
                    <input
                      value={editForm.short_name}
                      onChange={(e) => setEditForm({ ...editForm, short_name: e.target.value })}
                      className="w-full px-2 py-1.5 border rounded text-sm"
                      placeholder="短縮名"
                    />
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={() => setEditingId(null)}
                        disabled={savingId === t.id}
                        className="p-2 text-gray-500 border rounded disabled:opacity-50"
                      >
                        <X size={16} />
                      </button>
                      <button
                        onClick={() => handleSave(t.id)}
                        disabled={savingId === t.id}
                        className="p-2 bg-green-600 text-white rounded inline-flex items-center gap-1 disabled:opacity-60"
                      >
                        {savingId === t.id ? <Loader2 size={14} className="animate-spin" /> : <Check size={16} />}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate">{t.name}</div>
                        <div className="text-xs text-gray-500 mt-0.5 flex flex-wrap gap-x-2">
                          <code className="bg-gray-100 px-1 rounded">{t.display_id || '—'}</code>
                          {t.short_name && <span>({t.short_name})</span>}
                          {t.is_independent ? (
                            <span className="px-1.5 rounded bg-yellow-100 text-yellow-700">無所属</span>
                          ) : (
                            <span className="px-1.5 rounded bg-blue-100 text-blue-700">チーム</span>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button
                          onClick={() => setExpandedTeamId((cur) => (cur === t.id ? null : t.id))}
                          className="p-1.5 text-gray-600 border rounded inline-flex items-center gap-1"
                        >
                          <Users size={14} />
                          <span className="text-xs">{members.length}</span>
                        </button>
                        {(isAdmin || isCoach) && (
                          <button
                            onClick={() => startEdit(t)}
                            className="p-1.5 text-blue-600 border rounded"
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                    {expanded && (
                      <div className="mt-3 pt-3 border-t">
                        <div className="text-xs text-gray-500 mb-1">メンバー（{members.length} 名）</div>
                        {members.length === 0 ? (
                          <div className="text-xs text-gray-400">所属ユーザーはいません。</div>
                        ) : (
                          <ul className="space-y-1 text-sm">
                            {members.map((u) => (
                              <li key={u.id} className="flex items-center gap-2">
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-200 text-gray-700">{u.role}</span>
                                <span className="truncate">{u.display_name || u.username}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-left border-b">
              <th className="py-2 pr-2">ID</th>
              <th className="py-2 pr-2">識別子</th>
              <th className="py-2 pr-2">表示名</th>
              <th className="py-2 pr-2">短縮名</th>
              <th className="py-2 pr-2">種別</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {teams.map((t) => {
              const editing = editingId === t.id
              const canEdit = isAdmin || (isCoach && false) // coach は自チームのみ。サーバ側で権限制御。
              return (
                <tr key={t.id} className="border-b">
                  <td className="py-2 pr-2 text-xs text-gray-500">{t.id}</td>
                  <td className="py-2 pr-2">
                    {editing ? (
                      <input
                        value={editForm.display_id}
                        onChange={(e) => setEditForm({ ...editForm, display_id: e.target.value })}
                        className="w-full px-2 py-1 border rounded text-sm"
                      />
                    ) : (
                      <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{t.display_id || '—'}</code>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    {editing ? (
                      <input
                        value={editForm.name}
                        onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                        className="w-full px-2 py-1 border rounded text-sm"
                      />
                    ) : (
                      <span>{t.name}</span>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    {editing ? (
                      <input
                        value={editForm.short_name}
                        onChange={(e) => setEditForm({ ...editForm, short_name: e.target.value })}
                        className="w-full px-2 py-1 border rounded text-sm"
                      />
                    ) : (
                      <span className="text-sm text-gray-600">{t.short_name || '—'}</span>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-xs">
                    {t.is_independent ? (
                      <span className="px-2 py-0.5 rounded bg-yellow-100 text-yellow-700">無所属</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded bg-blue-100 text-blue-700">チーム</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    <div className="flex gap-1 justify-end items-center">
                      {!editing && (
                        <button
                          onClick={() => setExpandedTeamId((cur) => (cur === t.id ? null : t.id))}
                          className="p-1 text-gray-600 hover:bg-gray-100 rounded inline-flex items-center gap-1"
                          title="メンバー一覧を表示"
                        >
                          <Users size={14} />
                          <span className="text-xs">{(usersByTeam[t.id] || []).length}</span>
                        </button>
                      )}
                      {editing ? (
                        <>
                          <button
                            onClick={() => handleSave(t.id)}
                            disabled={savingId === t.id}
                            className="p-1 text-green-600 hover:bg-green-50 rounded disabled:opacity-50"
                            title="保存"
                          >
                            {savingId === t.id ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                          </button>
                          <button
                            onClick={() => setEditingId(null)}
                            className="p-1 text-gray-500 hover:bg-gray-50 rounded"
                            title="キャンセル"
                          >
                            <X size={16} />
                          </button>
                        </>
                      ) : canEdit || isCoach ? (
                        <button
                          onClick={() => startEdit(t)}
                          className="p-1 text-blue-600 hover:bg-blue-50 rounded"
                          title="編集"
                        >
                          <Pencil size={16} />
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              )
            })}
            {teams.map((t) => {
              if (expandedTeamId !== t.id) return null
              const members = usersByTeam[t.id] || []
              return (
                <tr key={`${t.id}-members-row`} className="bg-gray-50/60">
                  <td colSpan={6} className="px-4 py-2">
                    <div className="text-xs text-gray-500 mb-1">「{t.name}」のメンバー（{members.length} 名）</div>
                    {members.length === 0 ? (
                      <div className="text-xs text-gray-400">所属ユーザーはいません。</div>
                    ) : (
                      <ul className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-1 text-sm">
                        {members.map((u) => (
                          <li key={u.id} className="flex items-center gap-2">
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-200 text-gray-700">{u.role}</span>
                            <span>{u.display_name || u.username}</span>
                            <span className="text-xs text-gray-400">@{u.username}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              )
            })}
            {teams.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-sm text-gray-500">
                  表示できるチームがありません。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
