import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Pencil, Plus, Trash2, X, Check, KeyRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { apiDelete, apiGet, apiPost, apiPut, authAdminResetPassword, getUserPageAccess, setUserPageAccess, getTeamPageAccess, setTeamPageAccess } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useIsLightMode } from '@/hooks/useIsLightMode'

const PAGE_ACCESS_OPTIONS = [
  { key: 'prediction', labelKey: 'users.manage.page_access_prediction' },
  { key: 'expert_labeler', labelKey: 'users.manage.page_access_expert_labeler' },
] as const

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

const ROLE_KEYS: Record<string, string> = {
  admin: 'users.manage.role.admin',
  analyst: 'users.manage.role.analyst',
  coach: 'users.manage.role.coach',
  player: 'users.manage.role.player',
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
  const { t } = useTranslation()
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
          title={visible ? t('users.manage.pw_hide') : t('users.manage.pw_show')}
          aria-label={visible ? t('users.manage.pw_aria_hide') : t('users.manage.pw_aria_show')}
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
  const { t } = useTranslation()
  const [resetResult, setResetResult] = useState<{ username: string; password: string } | null>(null)
  const [resetBusyId, setResetBusyId] = useState<number | null>(null)
  const [copyDone, setCopyDone] = useState(false)

  const handleResetPassword = async (u: UserRow) => {
    if (!window.confirm(t('users.manage.reset_confirm', { name: u.display_name || u.username }))) return
    setResetBusyId(u.id)
    setCopyDone(false)
    try {
      const res = await authAdminResetPassword(u.id)
      setResetResult({ username: u.username, password: res.temporary_password })
    } catch (err) {
      const e = err as Error
      window.alert(e.message || 'error')
    } finally {
      setResetBusyId(null)
    }
  }

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
  const [editPageAccess, setEditPageAccess] = useState<string[]>([])
  const [editTeamPageAccess, setEditTeamPageAccess] = useState<string[]>([])
  const [editingTeamName, setEditingTeamName] = useState<string | null>(null)

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
      return editId != null ? t('users.manage.credential_player_update') : t('users.manage.credential_player_new')
    }
    return editId != null ? t('users.manage.credential_update') : t('users.manage.credential_new')
  }, [editId, isPlayerRole, t])

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
    return <div className="p-8 text-center text-gray-500">{t('users.manage.no_permission')}</div>
  }

  const openCreate = () => {
    setForm(emptyForm())
    setEditId(null)
    setError(null)
    setShowForm(true)
  }

  const openEdit = async (u: UserRow) => {
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
    setEditPageAccess([])
    setEditTeamPageAccess([])
    setEditingTeamName(null)
    if (u.role === 'player') {
      try {
        const res = await getUserPageAccess(u.id)
        setEditPageAccess(res.data ?? [])
      } catch { /* ignore */ }
      if (u.team_name) {
        setEditingTeamName(u.team_name)
        try {
          const tr = await getTeamPageAccess(u.team_name)
          setEditTeamPageAccess(tr.data ?? [])
        } catch { /* ignore */ }
      }
    }
    setShowForm(true)
  }

  const handleSave = async () => {
    if (!form.display_name.trim()) {
      setError(t('users.manage.validate_display_name'))
      return
    }
    if (!form.username.trim()) {
      setError(t('users.manage.validate_username'))
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
        if (form.role === 'player' && !isSelfOnly) {
          await setUserPageAccess(editId, editPageAccess)
          if (editingTeamName) {
            await setTeamPageAccess(editingTeamName, editTeamPageAccess)
          }
        }
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
    if (!window.confirm(t('users.manage.delete_confirm', { name: targetName }))) return
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
          <h1 className={`text-base font-semibold ${textMain}`}>{t('users.manage.title')}</h1>
          {isSelfOnly && (
            <p className={`text-xs mt-0.5 ${textMuted}`}>{t('users.manage.self_only_hint')}</p>
          )}
          {myRole === 'coach' && (
            <p className={`text-xs mt-0.5 ${textMuted}`}>{t('users.manage.coach_hint')}</p>
          )}
        </div>
        {canCreate && (
          <button
            onClick={openCreate}
            className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-3 py-1.5 rounded-lg"
          >
            <Plus size={14} />
            {t('users.manage.add_user')}
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
              <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.search')}</label>
              <input
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className={inputCls}
                placeholder={t('users.manage.search_placeholder')}
              />
            </div>
            <div>
              <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.sort')}</label>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
                className={inputCls}
              >
                <option value="display_name">{t('users.manage.sort_display_name')}</option>
                <option value="username">{t('users.manage.sort_username')}</option>
                <option value="player_name">{t('users.manage.sort_player_name')}</option>
              </select>
            </div>
          </div>
        </div>

        {showForm ? (
          <div className={`mb-6 ${panelBg} border ${border} rounded-xl p-5`}>
            <div className="flex items-center justify-between mb-4">
              <h2 className={`text-sm font-semibold ${textMain}`}>
                {editId != null ? t('users.manage.edit_title') : t('users.manage.create_title')}
              </h2>
              <button onClick={() => setShowForm(false)} className={textMuted}>
                <X size={16} />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {editId == null && canCreate ? (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.role_label')}</label>
                  <select
                    value={form.role}
                    onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                    className={inputCls}
                  >
                    {['admin', 'analyst', 'coach', 'player'].map((r) => (
                      <option key={r} value={r}>
                        {t(ROLE_KEYS[r])}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              <div>
                <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.display_name')}</label>
                <input
                  value={form.display_name}
                  onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
                  className={inputCls}
                  placeholder={t('users.manage.display_name_placeholder')}
                />
              </div>

              {!isSelfOnly && (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.username_label')}</label>
                  <input
                    value={form.username}
                    onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                    className={inputCls}
                    placeholder={t('users.manage.username_placeholder')}
                    disabled={isSelfOnly}
                  />
                  <p className={`mt-1 text-xs ${textMuted}`}>
                    {t('users.manage.username_hint')}
                  </p>
                </div>
              )}

              <SecretField
                label={credentialLabel}
                value={form.credential}
                onChange={(value) => setForm((f) => ({ ...f, credential: value }))}
                placeholder={isPlayerRole ? t('users.manage.credential_placeholder_player') : t('users.manage.credential_placeholder_default')}
                autoComplete="new-password"
                inputMode={isPlayerRole ? 'text' : undefined}
                hint={
                  editId != null
                    ? t('users.manage.credential_hint_update')
                    : isPlayerRole
                      ? t('users.manage.credential_hint_player_new')
                      : undefined
                }
                isLight={isLight}
                textMuted={textMuted}
                inputCls={inputCls}
              />

              {isCoachRole ? (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.team_name')}</label>
                  <input
                    value={form.team_name}
                    onChange={(e) => setForm((f) => ({ ...f, team_name: e.target.value }))}
                    className={inputCls}
                    placeholder={t('users.manage.team_name_placeholder')}
                  />
                </div>
              ) : null}

              {isPlayerRole ? (
                <div>
                  <label className={`block text-xs font-medium mb-1 ${textMuted}`}>{t('users.manage.player_link')}</label>
                  <select
                    value={form.player_id}
                    onChange={(e) => setForm((f) => ({ ...f, player_id: e.target.value }))}
                    className={inputCls}
                  >
                    <option value="">{t('users.manage.player_unselected')}</option>
                    {players.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
            </div>

            {isPlayerRole && editId != null && !isSelfOnly ? (
              <div className={`mt-4 pt-4 border-t ${border}`}>
                <p className={`text-xs font-semibold mb-2 ${textMain}`}>{t('users.manage.page_access')}</p>
                <div className="space-y-3">
                  {PAGE_ACCESS_OPTIONS.map(({ key, labelKey }) => {
                    const indiv = editPageAccess.includes(key)
                    const team = editTeamPageAccess.includes(key)
                    return (
                      <div key={key} className="flex flex-col gap-1">
                        <span className={`text-xs font-medium ${textMuted}`}>{t(labelKey)}</span>
                        <div className="flex flex-wrap gap-3">
                          <label className={`flex items-center gap-1.5 text-xs cursor-pointer ${textMuted}`}>
                            <input
                              type="checkbox"
                              checked={indiv}
                              onChange={(e) =>
                                setEditPageAccess((prev) =>
                                  e.target.checked ? [...prev, key] : prev.filter((k) => k !== key)
                                )
                              }
                            />
                            {t('users.manage.individual')}
                          </label>
                          {editingTeamName ? (
                            <label className={`flex items-center gap-1.5 text-xs cursor-pointer ${textMuted}`}>
                              <input
                                type="checkbox"
                                checked={team}
                                onChange={(e) =>
                                  setEditTeamPageAccess((prev) =>
                                    e.target.checked ? [...prev, key] : prev.filter((k) => k !== key)
                                  )
                                }
                              />
                              {t('users.manage.team_whole', { team: editingTeamName })}
                            </label>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ) : null}

            <div className="mt-4 flex gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded-lg"
              >
                <Check size={14} />
                {saving ? t('users.manage.saving') : t('users.manage.save')}
              </button>
              <button
                onClick={() => setShowForm(false)}
                className={`text-sm px-4 py-1.5 rounded-lg border ${border} ${textMuted}`}
              >
                {t('users.manage.cancel')}
              </button>
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className={`text-sm ${textMuted}`}>{t('users.manage.loading')}</div>
        ) : (
          <div className={`${panelBg} border ${border} rounded-xl overflow-hidden`}>
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b ${border} text-left`}>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted}`}>{t('users.manage.col_role')}</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted}`}>{t('users.manage.col_display_name')}</th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted} hidden sm:table-cell`}>
                    {t('users.manage.col_account')}
                  </th>
                  <th className={`px-4 py-2.5 text-xs font-medium ${textMuted} hidden sm:table-cell`}>{t('users.manage.col_credential')}</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((u) => (
                  <tr key={u.id} className={`border-b last:border-0 ${border} ${rowHover}`}>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${ROLE_COLORS[u.role] ?? 'bg-gray-100 text-gray-600'}`}>
                        {ROLE_KEYS[u.role] ? t(ROLE_KEYS[u.role]) : u.role}
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-medium ${textMain}`}>{u.display_name ?? '—'}</td>
                    <td className={`px-4 py-2.5 ${textMuted} text-xs hidden sm:table-cell`}>
                      <div>{u.username || '—'}</div>
                      {u.role === 'coach' ? <div>{t('users.manage.team_prefix')}: {u.team_name || '—'}</div> : null}
                      {u.role === 'player' ? <div>{t('users.manage.player_prefix')}: {u.player_name || '—'}</div> : null}
                    </td>
                    <td className={`px-4 py-2.5 text-xs ${textMuted} hidden sm:table-cell`}>
                      {u.has_credential ? t('users.manage.credential_set') : t('users.manage.credential_unset')}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2 justify-end">
                        <button onClick={() => openEdit(u)} className={`${textMuted} hover:text-blue-500`}>
                          <Pencil size={14} />
                        </button>
                        {myRole === 'admin' && (
                          <button
                            onClick={() => handleResetPassword(u)}
                            disabled={resetBusyId === u.id}
                            title={t('auth.admin_reset.title')}
                            className={`${textMuted} hover:text-amber-500 disabled:opacity-50`}
                          >
                            <KeyRound size={14} />
                          </button>
                        )}
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
                      {searchTerm.trim() ? t('users.manage.empty_search') : t('users.manage.empty_all')}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {resetResult && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className={`w-full max-w-md rounded-lg p-5 ${isLight ? 'bg-white text-gray-900' : 'bg-gray-800 text-white'}`}>
            <h3 className="text-lg font-semibold mb-2">{t('auth.admin_reset.result_title')}</h3>
            <p className={`text-xs mb-3 ${textMuted}`}>
              {resetResult.username}
            </p>
            <div className={`font-mono text-sm break-all rounded px-3 py-2 mb-3 ${isLight ? 'bg-gray-100' : 'bg-gray-900'}`}>
              {resetResult.password}
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(resetResult.password)
                    setCopyDone(true)
                  } catch { /* ignore */ }
                }}
                className={`px-3 py-1.5 rounded text-sm ${isLight ? 'bg-blue-600 text-white hover:bg-blue-500' : 'bg-blue-700 text-white hover:bg-blue-600'}`}
              >
                {copyDone ? t('auth.admin_reset.copied') : t('auth.admin_reset.copy')}
              </button>
              <button
                onClick={() => { setResetResult(null); setCopyDone(false) }}
                className={`px-3 py-1.5 rounded text-sm ${isLight ? 'bg-gray-200 text-gray-700 hover:bg-gray-300' : 'bg-gray-700 text-gray-200 hover:bg-gray-600'}`}
              >
                {t('auth.admin_reset.close')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
