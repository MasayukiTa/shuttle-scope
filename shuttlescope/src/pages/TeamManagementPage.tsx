import { useEffect, useMemo, useState } from 'react'
import {
  listTeams,
  createTeam,
  patchTeam,
  apiGet,
  deleteTeam,
  getTeamDependencies,
  type TeamDTO,
  type TeamDependencies,
} from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { useAuth } from '@/hooks/useAuth'
import { useIsMobile } from '@/hooks/useIsMobile'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()

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

  // 削除確認用 state（Round 258 #16）
  const [deleteTarget, setDeleteTarget] = useState<TeamDTO | null>(null)
  const [deleteDeps, setDeleteDeps] = useState<TeamDependencies | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

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

  /**
   * 削除フロー (Round 258 #16):
   * 1. 削除ボタン押下 → GET /teams/{id}/dependencies で users/players/matches 件数を取得
   * 2. モーダル表示 (依存数・force 選択)
   * 3. 確定で DELETE /teams/{id}?force=... 実行 → 成功で再 load
   */
  const startDelete = async (t: TeamDTO) => {
    if (!isAdmin) return
    setDeleteTarget(t)
    setDeleteDeps(null)
    try {
      const res = await getTeamDependencies(t.id)
      setDeleteDeps(res.data)
    } catch (e) {
      setError(e instanceof Error ? e.message : '依存関係の取得に失敗しました')
      setDeleteTarget(null)
    }
  }

  const confirmDelete = async (force: boolean) => {
    if (!deleteTarget) return
    setDeletingId(deleteTarget.id)
    try {
      await deleteTeam(deleteTarget.id, force)
      setDeleteTarget(null)
      setDeleteDeps(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'チーム削除に失敗しました')
    } finally {
      setDeletingId(null)
    }
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
        <p className="text-sm text-[var(--ss-t3)]">{t('auto.TeamManagementPage.k1')}</p>
      </div>
    )
  }

  return (
    <div className="p-3 sm:p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-4 gap-2">
        <h1 className="text-xl font-bold truncate">{t('auto.TeamManagementPage.k2')}</h1>
        {isAdmin && (
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 px-3 py-2 bg-[var(--ss-brand)] text-white rounded-ss-md hover:bg-[var(--ss-brand-hover)] shrink-0"
          >
            <MIcon name="add" size={16} /> <span className="hidden sm:inline">{t('auto.TeamManagementPage.k3')}</span><span className="sm:hidden">{t('auto.TeamManagementPage.k4')}</span>
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-[var(--ss-danger-bg)] border border-[var(--ss-danger-border)] text-[var(--ss-danger-text)] text-sm rounded-ss-lg">
          {error}
        </div>
      )}

      {showCreate && (
        <div className="mb-6 p-4 border border-[var(--ss-border)] rounded-ss-lg bg-[var(--ss-surface-2)]">
          <h2 className="font-semibold mb-3 text-[var(--ss-t1)]">{t('auto.TeamManagementPage.k5')}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium mb-1 text-[var(--ss-t2)]">{t('auto.TeamManagementPage.k6')}</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full px-3 py-2 border border-[var(--ss-border)] rounded-ss-md bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                placeholder={t('auto.TeamManagementPage.k25')}
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-[var(--ss-t2)]">{t('auto.TeamManagementPage.k7')}</label>
              <input
                value={form.display_id}
                onChange={(e) => setForm({ ...form, display_id: e.target.value })}
                className="w-full px-3 py-2 border border-[var(--ss-border)] rounded-ss-md bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                placeholder={t('auto.TeamManagementPage.k26')}
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-[var(--ss-t2)]">{t('auto.TeamManagementPage.k8')}</label>
              <input
                value={form.short_name}
                onChange={(e) => setForm({ ...form, short_name: e.target.value })}
                className="w-full px-3 py-2 border border-[var(--ss-border)] rounded-ss-md bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs font-medium mb-1 text-[var(--ss-t2)]">{t('auto.TeamManagementPage.k9')}</label>
              <textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                className="w-full px-3 py-2 border border-[var(--ss-border)] rounded-ss-md bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
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
              className="px-3 py-2 border border-[var(--ss-border-strong)] rounded-ss-md text-[var(--ss-t1)] bg-[var(--ss-surface-1)] disabled:opacity-50 w-full sm:w-auto"
            >
              {t('auto.TeamManagementPage.k23')}
            </button>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-3 py-2 bg-[var(--ss-brand)] text-white rounded-ss-md disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center justify-center gap-2 w-full sm:w-auto"
            >
              {creating && <MIcon name="progress_activity" size={14} className="animate-spin" />}
              {creating ? t('auto.TeamManagementPage.k27') : t('auto.TeamManagementPage.k28')}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-[var(--ss-t3)]">{t('auto.TeamManagementPage.k10')}</p>
      ) : isMobile ? (
        <div className="space-y-2">
          {teams.length === 0 && (
            <div className="py-6 text-center text-sm text-[var(--ss-t3)]">{t('auto.TeamManagementPage.k11')}</div>
          )}
          {teams.map((tm) => {
            const editing = editingId === tm.id
            const expanded = expandedTeamId === tm.id
            const members = usersByTeam[tm.id] || []
            return (
              <div key={tm.id} className="border border-[var(--ss-border)] rounded-ss-lg p-3 bg-[var(--ss-surface-1)]">
                {editing ? (
                  <div className="space-y-2">
                    <input
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="w-full px-2 py-1.5 border border-[var(--ss-border)] rounded-ss-md text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                      placeholder={t('auto.TeamManagementPage.k16')}
                    />
                    <input
                      value={editForm.display_id}
                      onChange={(e) => setEditForm({ ...editForm, display_id: e.target.value })}
                      className="w-full px-2 py-1.5 border border-[var(--ss-border)] rounded-ss-md text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                      placeholder={t('auto.TeamManagementPage.k15')}
                    />
                    <input
                      value={editForm.short_name}
                      onChange={(e) => setEditForm({ ...editForm, short_name: e.target.value })}
                      className="w-full px-2 py-1.5 border border-[var(--ss-border)] rounded-ss-md text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                      placeholder={t('auto.TeamManagementPage.k8')}
                    />
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={() => setEditingId(null)}
                        disabled={savingId === tm.id}
                        className="p-2 text-[var(--ss-t2)] border border-[var(--ss-border)] rounded-ss-md disabled:opacity-50"
                      >
                        <MIcon name="close" size={16} />
                      </button>
                      <button
                        onClick={() => handleSave(tm.id)}
                        disabled={savingId === tm.id}
                        className="p-2 bg-[var(--ss-success)] text-white rounded-ss-md inline-flex items-center gap-1 disabled:opacity-60"
                      >
                        {savingId === tm.id ? <MIcon name="progress_activity" size={14} className="animate-spin" /> : <MIcon name="check" size={16} />}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate text-[var(--ss-t1)]">{tm.name}</div>
                        <div className="text-xs text-[var(--ss-t3)] mt-0.5 flex flex-wrap gap-x-2">
                          <code className="bg-[var(--ss-surface-2)] px-1 rounded">{tm.display_id || '—'}</code>
                          {tm.short_name && <span>({tm.short_name})</span>}
                          {tm.is_independent ? (
                            <span className="px-1.5 rounded-ss-sm bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]">{t('auto.TeamManagementPage.k12')}</span>
                          ) : (
                            <span className="px-1.5 rounded-ss-sm bg-[var(--ss-brand-tint)] text-[var(--ss-brand)]">{t('auto.TeamManagementPage.k13')}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button
                          onClick={() => setExpandedTeamId((cur) => (cur === tm.id ? null : tm.id))}
                          className="p-1.5 text-[var(--ss-t2)] border border-[var(--ss-border)] rounded-ss-md inline-flex items-center gap-1"
                        >
                          <MIcon name="group" size={14} />
                          <span className="text-xs">{members.length}</span>
                        </button>
                        {(isAdmin || isCoach) && (
                          <button
                            onClick={() => startEdit(tm)}
                            className="p-1.5 text-[var(--ss-brand)] border border-[var(--ss-border)] rounded-ss-md"
                          >
                            <MIcon name="edit" size={14} />
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            onClick={() => startDelete(tm)}
                            disabled={deletingId === tm.id}
                            className="p-1.5 text-[var(--ss-danger-text)] border border-[var(--ss-border)] rounded-ss-md disabled:opacity-50"
                            title={t('auto.TeamManagementPage.k20')}
                          >
                            {deletingId === tm.id ? (
                              <MIcon name="progress_activity" size={14} className="animate-spin" />
                            ) : (
                              <MIcon name="delete" size={14} />
                            )}
                          </button>
                        )}
                      </div>
                    </div>
                    {expanded && (
                      <div className="mt-3 pt-3 border-t border-[var(--ss-border)]">
                        <div className="text-xs text-[var(--ss-t3)] mb-1">{t('auto.TeamManagementPage.k29', { n: members.length })}</div>
                        {members.length === 0 ? (
                          <div className="text-xs text-[var(--ss-t3)]">{t('auto.TeamManagementPage.k14')}</div>
                        ) : (
                          <ul className="space-y-1 text-sm">
                            {members.map((u) => (
                              <li key={u.id} className="flex items-center gap-2">
                                <span className="px-1.5 py-0.5 rounded-ss-sm text-[10px] bg-[var(--ss-surface-2)] text-[var(--ss-t2)]">{u.role}</span>
                                <span className="truncate text-[var(--ss-t1)]">{u.display_name || u.username}</span>
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
            <tr className="text-left border-b border-[var(--ss-border)] bg-[var(--ss-surface-2)]">
              <th className="py-2 pr-2 text-[var(--ss-t1)]">ID</th>
              <th className="py-2 pr-2 text-[var(--ss-t1)]">{t('auto.TeamManagementPage.k15')}</th>
              <th className="py-2 pr-2 text-[var(--ss-t1)]">{t('auto.TeamManagementPage.k16')}</th>
              <th className="py-2 pr-2 text-[var(--ss-t1)]">{t('auto.TeamManagementPage.k8')}</th>
              <th className="py-2 pr-2 text-[var(--ss-t1)]">{t('auto.TeamManagementPage.k17')}</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {teams.map((tm) => {
              const editing = editingId === tm.id
              const canEdit = isAdmin || (isCoach && false) // coach は自チームのみ。サーバ側で権限制御。
              return (
                <tr key={tm.id} className="border-b border-[var(--ss-border)] bg-[var(--ss-surface-1)]">
                  <td className="py-2 pr-2 text-xs ss-num text-[var(--ss-t3)]">{tm.id}</td>
                  <td className="py-2 pr-2">
                    {editing ? (
                      <input
                        value={editForm.display_id}
                        onChange={(e) => setEditForm({ ...editForm, display_id: e.target.value })}
                        className="w-full px-2 py-1 border border-[var(--ss-border)] rounded-ss-md text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                      />
                    ) : (
                      <code className="text-xs bg-[var(--ss-surface-2)] px-2 py-0.5 rounded-ss-sm text-[var(--ss-t2)]">{tm.display_id || '—'}</code>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    {editing ? (
                      <input
                        value={editForm.name}
                        onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                        className="w-full px-2 py-1 border border-[var(--ss-border)] rounded-ss-md text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                      />
                    ) : (
                      <span className="text-[var(--ss-t1)]">{tm.name}</span>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    {editing ? (
                      <input
                        value={editForm.short_name}
                        onChange={(e) => setEditForm({ ...editForm, short_name: e.target.value })}
                        className="w-full px-2 py-1 border border-[var(--ss-border)] rounded-ss-md text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
                      />
                    ) : (
                      <span className="text-sm text-[var(--ss-t2)]">{tm.short_name || '—'}</span>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-xs">
                    {tm.is_independent ? (
                      <span className="px-2 py-0.5 rounded-ss-sm bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]">{t('auto.TeamManagementPage.k12')}</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-ss-sm bg-[var(--ss-brand-tint)] text-[var(--ss-brand)]">{t('auto.TeamManagementPage.k13')}</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    <div className="flex gap-1 justify-end items-center">
                      {!editing && (
                        <button
                          onClick={() => setExpandedTeamId((cur) => (cur === tm.id ? null : tm.id))}
                          className="p-1 text-[var(--ss-t2)] border border-[var(--ss-border)] rounded-ss-md inline-flex items-center gap-1"
                          title={t('auto.TeamManagementPage.k21')}
                        >
                          <MIcon name="group" size={14} />
                          <span className="text-xs">{(usersByTeam[tm.id] || []).length}</span>
                        </button>
                      )}
                      {editing ? (
                        <>
                          <button
                            onClick={() => handleSave(tm.id)}
                            disabled={savingId === tm.id}
                            className="p-1 text-[var(--ss-success)] border border-[var(--ss-border)] rounded-ss-md disabled:opacity-50"
                            title={t('auto.TeamManagementPage.k22')}
                          >
                            {savingId === tm.id ? <MIcon name="progress_activity" size={16} className="animate-spin" /> : <MIcon name="check" size={16} />}
                          </button>
                          <button
                            onClick={() => setEditingId(null)}
                            className="p-1 text-[var(--ss-t2)] border border-[var(--ss-border)] rounded-ss-md"
                            title={t('auto.TeamManagementPage.k23')}
                          >
                            <MIcon name="close" size={16} />
                          </button>
                        </>
                      ) : canEdit || isCoach ? (
                        <>
                          <button
                            onClick={() => startEdit(tm)}
                            className="p-1 text-[var(--ss-brand)] border border-[var(--ss-border)] rounded-ss-md"
                            title={t('auto.TeamManagementPage.k24')}
                          >
                            <MIcon name="edit" size={16} />
                          </button>
                          {isAdmin && (
                            <button
                              onClick={() => startDelete(tm)}
                              className="p-1 text-[var(--ss-danger-text)] border border-[var(--ss-border)] rounded-ss-md"
                              title={t('auto.TeamManagementPage.k20')}
                              disabled={deletingId === tm.id}
                            >
                              {deletingId === tm.id ? (
                                <MIcon name="progress_activity" size={16} className="animate-spin" />
                              ) : (
                                <MIcon name="delete" size={16} />
                              )}
                            </button>
                          )}
                        </>
                      ) : null}
                    </div>
                  </td>
                </tr>
              )
            })}
            {teams.map((tm) => {
              if (expandedTeamId !== tm.id) return null
              const members = usersByTeam[tm.id] || []
              return (
                <tr key={`${tm.id}-members-row`} className="bg-[var(--ss-surface-2)]">
                  <td colSpan={6} className="px-4 py-2">
                    <div className="text-xs text-[var(--ss-t3)] mb-1">{t('auto.TeamManagementPage.k30', { name: tm.name, n: members.length })}</div>
                    {members.length === 0 ? (
                      <div className="text-xs text-[var(--ss-t3)]">{t('auto.TeamManagementPage.k14')}</div>
                    ) : (
                      <ul className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-1 text-sm">
                        {members.map((u) => (
                          <li key={u.id} className="flex items-center gap-2">
                            <span className="px-1.5 py-0.5 rounded-ss-sm text-[10px] bg-[var(--ss-border)] text-[var(--ss-t2)]">{u.role}</span>
                            <span className="text-[var(--ss-t1)]">{u.display_name || u.username}</span>
                            <span className="text-xs text-[var(--ss-t3)]">@{u.username}</span>
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
                <td colSpan={6} className="py-6 text-center text-sm text-[var(--ss-t3)]">
                  {t('auto.TeamManagementPage.k11')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {/* 削除確認モーダル (Round 258 #16) */}
      {deleteTarget && (
        <div
          className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
          onClick={() => {
            if (deletingId == null) {
              setDeleteTarget(null)
              setDeleteDeps(null)
            }
          }}
        >
          <div
            className="bg-[var(--ss-surface-1)] rounded-ss-lg shadow-card border border-[var(--ss-border)] max-w-md w-full p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3">
              <MIcon name="warning" size={20} className="text-[var(--ss-danger-text)]" />
              <h2 className="text-lg font-semibold text-[var(--ss-t1)]">{t('auto.TeamManagementPage.k18')}</h2>
            </div>
            <p className="text-sm text-[var(--ss-t2)] mb-3">
              {t('auto.TeamManagementPage.k31')}「<span className="font-medium">{deleteTarget.name}</span>」{t('auto.TeamManagementPage.k32')}
            </p>

            {!deleteDeps ? (
              <div className="text-sm text-[var(--ss-t3)] flex items-center gap-2 py-2">
                <MIcon name="progress_activity" size={14} className="animate-spin" /> {t('auto.TeamManagementPage.k33')}
              </div>
            ) : (
              <div className="mb-4">
                <div className="text-xs text-[var(--ss-t3)] mb-1">{t('auto.TeamManagementPage.k19')}</div>
                <ul className="text-sm space-y-0.5 mb-3 text-[var(--ss-t2)]">
                  <li>
                    {t('auto.TeamManagementPage.k34')}{' '}
                    <span className={deleteDeps.counts.users ? 'font-medium ss-num text-[var(--ss-danger-text)]' : 'ss-num text-[var(--ss-t3)]'}>
                      {deleteDeps.counts.users}
                    </span>{' '}
                    {t('auto.TeamManagementPage.k35')}
                  </li>
                  <li>
                    {t('auto.TeamManagementPage.k36')}{' '}
                    <span
                      className={deleteDeps.counts.players ? 'font-medium ss-num text-[var(--ss-danger-text)]' : 'ss-num text-[var(--ss-t3)]'}
                    >
                      {deleteDeps.counts.players}
                    </span>{' '}
                    {t('auto.TeamManagementPage.k35')}
                  </li>
                  <li>
                    {t('auto.TeamManagementPage.k37')}{' '}
                    <span
                      className={deleteDeps.counts.matches ? 'font-medium ss-num text-[var(--ss-danger-text)]' : 'ss-num text-[var(--ss-t3)]'}
                    >
                      {deleteDeps.counts.matches}
                    </span>{' '}
                    {t('auto.TeamManagementPage.k38')}
                  </li>
                </ul>
                {(deleteDeps.counts.users ||
                  deleteDeps.counts.players ||
                  deleteDeps.counts.matches) > 0 ? (
                  <div className="text-xs bg-[var(--ss-warning-bg)] border border-[var(--ss-warning-border)] text-[var(--ss-warning-text)] p-2 rounded-ss-sm">
                    {t('auto.TeamManagementPage.k39')}
                  </div>
                ) : (
                  <div className="text-xs bg-[var(--ss-success-bg)] border border-[var(--ss-success-border)] text-[var(--ss-success-text)] p-2 rounded-ss-sm">
                    {t('auto.TeamManagementPage.k40')}
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  if (deletingId == null) {
                    setDeleteTarget(null)
                    setDeleteDeps(null)
                  }
                }}
                disabled={deletingId != null}
                className="px-3 py-2 border border-[var(--ss-border-strong)] rounded-ss-md text-[var(--ss-t1)] bg-[var(--ss-surface-1)] disabled:opacity-50"
              >
                {t('auto.TeamManagementPage.k23')}
              </button>
              {deleteDeps &&
                (deleteDeps.counts.users ||
                  deleteDeps.counts.players ||
                  deleteDeps.counts.matches) > 0 && (
                  <button
                    onClick={() => confirmDelete(true)}
                    disabled={deletingId != null}
                    className="px-3 py-2 bg-[var(--ss-emphasis)] text-white rounded-ss-md disabled:opacity-60 inline-flex items-center gap-2"
                  >
                    {deletingId != null && <MIcon name="progress_activity" size={14} className="animate-spin" />}
                    {t('auto.TeamManagementPage.k41')}
                  </button>
                )}
              {deleteDeps &&
                deleteDeps.counts.users === 0 &&
                deleteDeps.counts.players === 0 &&
                deleteDeps.counts.matches === 0 && (
                  <button
                    onClick={() => confirmDelete(false)}
                    disabled={deletingId != null}
                    className="px-3 py-2 bg-[var(--ss-bad)] text-white rounded-ss-md disabled:opacity-60 inline-flex items-center gap-2"
                  >
                    {deletingId != null && <MIcon name="progress_activity" size={14} className="animate-spin" />}
                    {t('auto.TeamManagementPage.k20')}
                  </button>
                )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
