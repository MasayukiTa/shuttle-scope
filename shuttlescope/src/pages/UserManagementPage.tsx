import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Pencil, Plus, Trash2, X, Check, KeyRound, ChevronDown, RotateCcw, AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { apiDelete, apiGet, apiPost, apiPut, authAdminResetPassword, getUserPageAccess, setUserPageAccess, getTeamPageAccess, setTeamPageAccess, listTeams, type TeamDTO } from '@/api/client'
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
  team_id: number | null
  team_display_id: string | null
  team_display_name: string | null
  team_is_independent: boolean | null
  player_id: number | null
  player_name: string | null
  has_credential: boolean
  created_at: string | null
}

interface PlayerOption {
  id: number
  name: string
}

interface LimitInfo {
  user_id: number
  active_uploads: number
  max_concurrent_uploads: number
  exfil_window_age_sec: number
  exfil_bytes: number
  exfil_requests: number
  exfil_alerted: boolean
  exfil_near_hard_block: boolean
  failed_attempts: number
  is_locked: boolean
  locked_until: string | null
  near_lock: boolean
  is_limited: boolean
}

interface FormState {
  role: string
  display_name: string
  username: string
  credential: string
  player_id: string
  team_name: string
  team_id: string
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
  team_id: '',
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
  type SortKey = 'display_name' | 'username' | 'player_name' | 'team_name' | 'active_uploads' | 'exfil_requests' | 'is_limited'

  const { role: myRole } = useAuth()
  const isLight = useIsLightMode()
  const { t } = useTranslation()
  const [resetResult, setResetResult] = useState<{ username: string; password: string } | null>(null)
  const [resetBusyId, setResetBusyId] = useState<number | null>(null)
  const [limits, setLimits] = useState<Record<number, LimitInfo>>({})
  const [limitResetBusyId, setLimitResetBusyId] = useState<number | null>(null)
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
  // showCreateForm: true = 新規作成パネルを表示
  const [showCreateForm, setShowCreateForm] = useState(false)
  // editId: インライン展開中のユーザーID（null = 展開なし）
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm())
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('display_name')
  const [editPageAccess, setEditPageAccess] = useState<string[]>([])
  const [editTeamPageAccess, setEditTeamPageAccess] = useState<string[]>([])
  const [editingTeamName, setEditingTeamName] = useState<string | null>(null)
  const [teams, setTeams] = useState<TeamDTO[]>([])

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const border = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMain = isLight ? 'text-gray-900' : 'text-gray-100'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowHover = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/50'
  const inputCls = `w-full border ${isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-700'} rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${textMain}`
  const inlinePanelBg = isLight ? 'bg-blue-50 border-blue-100' : 'bg-gray-750 border-blue-900/40'

  const isPlayerRole = form.role === 'player'
  const needsTeam = form.role !== 'admin'

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
      // 数値ソート (limit 列): is_limited 降順 → active_uploads 降順 → exfil_requests 降順
      if (sortKey === 'is_limited') {
        const al = limits[a.id]?.is_limited ? 1 : 0
        const bl = limits[b.id]?.is_limited ? 1 : 0
        return bl - al
      }
      if (sortKey === 'active_uploads') {
        return (limits[b.id]?.active_uploads ?? 0) - (limits[a.id]?.active_uploads ?? 0)
      }
      if (sortKey === 'exfil_requests') {
        return (limits[b.id]?.exfil_requests ?? 0) - (limits[a.id]?.exfil_requests ?? 0)
      }
      const aValue = ((a as unknown as Record<string, unknown>)[sortKey] ?? '').toString().toLowerCase()
      const bValue = ((b as unknown as Record<string, unknown>)[sortKey] ?? '').toString().toLowerCase()
      return aValue.localeCompare(bValue, 'ja')
    })
  }, [searchTerm, sortKey, users, limits])

  const load = async () => {
    setLoading(true)
    try {
      const [ur, pr, tr] = await Promise.all([
        apiGet<{ success: boolean; data: UserRow[] }>('/auth/users'),
        apiGet<{ success: boolean; data: { id: number; name: string }[] }>('/players?limit=500'),
        listTeams().catch(() => ({ success: false, data: [] as TeamDTO[] })),
      ])
      setUsers(ur.data ?? [])
      setPlayers(pr.data ?? [])
      setTeams(tr?.data ?? [])
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
    // admin 限定: rate-limit 状態を別途 fetch (失敗しても本体は壊さない)
    if (myRole === 'admin') {
      try {
        const lr = await apiGet<{ success: boolean; data: LimitInfo[] }>('/admin/security/user_limits')
        const map: Record<number, LimitInfo> = {}
        for (const r of lr.data ?? []) map[r.user_id] = r
        setLimits(map)
      } catch {
        // backend 旧版で endpoint が無い場合は無視 (UI 側は欠損として処理)
      }
    }
  }

  type LimitKind = 'all' | 'exfil' | 'uploads' | 'failed_attempts' | 'lock'
  const handleResetLimits = async (u: UserRow, kind: LimitKind = 'all') => {
    const labels: Record<LimitKind, string> = {
      all: '全部 (exfil / uploads / 失敗回数 / ロック)',
      exfil: 'EXFIL レート状態のみ',
      uploads: '進行中アップロードのみ',
      failed_attempts: 'ログイン失敗カウンタのみ',
      lock: 'アカウントロック解除のみ',
    }
    if (!window.confirm(`${u.display_name || u.username}: ${labels[kind]} をリセットしますか？`)) return
    setLimitResetBusyId(u.id)
    try {
      const body = kind === 'all'
        ? {}
        : { exfil: kind === 'exfil', uploads: kind === 'uploads', failed_attempts: kind === 'failed_attempts', lock: kind === 'lock' }
      await apiPost(`/admin/security/user_limits/${u.id}/reset`, body)
      await load()
    } catch (err) {
      window.alert((err as Error).message || 'reset error')
    } finally {
      setLimitResetBusyId(null)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const canCreate = myRole === 'admin' || myRole === 'analyst'
  const canDelete = myRole === 'admin'
  const isSelfOnly = myRole === 'player'

  if (!myRole) {
    return <div className="p-8 text-center text-gray-500">{t('users.manage.no_permission')}</div>
  }

  const closeAll = () => {
    setShowCreateForm(false)
    setEditId(null)
    setError(null)
  }

  const openCreate = () => {
    setForm(emptyForm())
    setEditId(null)
    setError(null)
    setShowCreateForm(true)
  }

  const openEdit = async (u: UserRow) => {
    // 同じ行を再度クリックしたら閉じる（トグル）
    if (editId === u.id) {
      setEditId(null)
      return
    }
    setShowCreateForm(false)
    setForm({
      role: u.role,
      display_name: u.display_name ?? '',
      username: u.username ?? '',
      credential: '',
      player_id: u.player_id ? String(u.player_id) : '',
      team_name: u.team_name ?? '',
      team_id: u.team_id ? String(u.team_id) : '',
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
    if (form.role !== 'admin' && !form.team_name.trim() && !form.team_id.trim()) {
      setError(t('users.manage.validate_team_name'))
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
        if (myRole === 'admin' && form.team_id.trim()) {
          body.team_id = parseInt(form.team_id, 10)
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
        if (myRole === 'admin' && form.team_id.trim()) {
          body.team_id = parseInt(form.team_id, 10)
        }
        if (form.credential.trim()) body.password = form.credential.trim()
        await apiPost('/auth/users', body)
      }
      closeAll()
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
      await apiDelete(`/auth/users/${u.id}`, { 'X-Idempotency-Key': newIdempotencyKey() })
      await load()
    } catch (e) {
      setError(String(e))
    }
  }

  // フォームフィールド群（新規作成・インライン編集の両方で共用）
  const renderFormFields = () => (
    <>
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
            <p className={`mt-1 text-xs ${textMuted}`}>{t('users.manage.username_hint')}</p>
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

        {needsTeam && myRole === 'admin' ? (
          <div className="col-span-2">
            <label className={`block text-xs font-medium mb-1 ${textMuted}`}>所属チーム</label>
            <select
              value={form.team_id}
              onChange={(e) => {
                const tid = e.target.value
                const selected = teams.find((tt) => String(tt.id) === tid)
                setForm((f) => ({
                  ...f,
                  team_id: tid,
                  team_name: selected ? selected.name : f.team_name,
                }))
              }}
              className={inputCls}
            >
              <option value="">— 既存チームから選択（または下に新規名を入力）—</option>
              {teams.map((tm) => (
                <option key={tm.id} value={tm.id}>
                  {tm.name} {tm.is_independent ? '［無所属］' : ''}
                </option>
              ))}
            </select>
            <input
              value={form.team_name}
              onChange={(e) => setForm((f) => ({
                ...f,
                team_name: e.target.value,
                team_id: e.target.value && f.team_id ? '' : f.team_id,
              }))}
              className={`${inputCls} mt-2`}
              placeholder={t('users.manage.team_name_placeholder')}
            />
            <p className={`mt-1 text-[11px] ${textMuted}`}>
              既存チームから選択するか、上にない新規チーム名を入力してください（自動作成）。
            </p>
          </div>
        ) : needsTeam ? (
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

      {error ? (
        <div className="mt-3 bg-red-50 border border-red-200 text-red-600 text-xs rounded px-3 py-2">
          {error}
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
          onClick={closeAll}
          className={`text-sm px-4 py-1.5 rounded-lg border ${border} ${textMuted}`}
        >
          {t('users.manage.cancel')}
        </button>
      </div>
    </>
  )

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
          {myRole === 'admin' && (
            <a href="#/users/pending"
               className="inline-block mt-1 text-xs text-blue-600 hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300">
              → 保留中ユーザー一覧 (admin 承認待ち)
            </a>
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
                <option value="team_name">{t('users.manage.sort_team_name')}</option>
              </select>
            </div>
          </div>
        </div>

        {/* 新規作成フォーム（上部パネル） */}
        {showCreateForm ? (
          <div className={`mb-6 ${panelBg} border ${border} rounded-xl p-5`}>
            <div className="flex items-center justify-between mb-4">
              <h2 className={`text-sm font-semibold ${textMain}`}>{t('users.manage.create_title')}</h2>
              <button onClick={closeAll} className={textMuted}>
                <X size={16} />
              </button>
            </div>
            {renderFormFields()}
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
                  {myRole === 'admin' && (
                    <>
                      <th
                        className={`px-3 py-2.5 text-xs font-medium ${textMuted} hidden md:table-cell cursor-pointer select-none`}
                        title="rate-limit がかかっているユーザを一目で確認 (クリックで降順ソート)"
                        onClick={() => setSortKey('is_limited')}
                      >
                        制限
                      </th>
                      <th
                        className={`px-3 py-2.5 text-xs font-medium ${textMuted} hidden md:table-cell cursor-pointer select-none`}
                        title="進行中アップロード件数 (上限 2)"
                        onClick={() => setSortKey('active_uploads')}
                      >
                        UL
                      </th>
                      <th
                        className={`px-3 py-2.5 text-xs font-medium ${textMuted} hidden lg:table-cell cursor-pointer select-none`}
                        title="直近 60 秒の API リクエスト数 (exfil rate)"
                        onClick={() => setSortKey('exfil_requests')}
                      >
                        req/60s
                      </th>
                    </>
                  )}
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((u) => (
                  <>
                    <tr key={u.id} className={`border-b last:border-0 ${border} ${editId === u.id ? (isLight ? 'bg-blue-50/60' : 'bg-blue-900/10') : rowHover}`}>
                      <td className="px-4 py-2.5">
                        <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${ROLE_COLORS[u.role] ?? 'bg-gray-100 text-gray-600'}`}>
                          {ROLE_KEYS[u.role] ? t(ROLE_KEYS[u.role]) : u.role}
                        </span>
                      </td>
                      <td className={`px-4 py-2.5 font-medium ${textMain}`}>{u.display_name ?? '—'}</td>
                      <td className={`px-4 py-2.5 ${textMuted} text-xs hidden sm:table-cell`}>
                        <div>{u.username || '—'}</div>
                        <div>
                          team: {u.team_display_name || u.team_name || '—'}
                          {u.team_display_id ? ` (${u.team_display_id})` : ''}
                          {u.team_is_independent ? ' ［無所属］' : ''}
                        </div>
                        {u.role === 'player' ? <div>{t('users.manage.player_prefix')}: {u.player_name || '—'}</div> : null}
                      </td>
                      <td className={`px-4 py-2.5 text-xs ${textMuted} hidden sm:table-cell`}>
                        {u.has_credential ? t('users.manage.credential_set') : t('users.manage.credential_unset')}
                      </td>
                      {myRole === 'admin' && (
                        <>
                          <td className="px-3 py-2.5 hidden md:table-cell">
                            {(() => {
                              const L = limits[u.id]
                              if (!L) return <span className={`text-xs ${textMuted}`}>—</span>
                              const badges: React.ReactElement[] = []
                              if (L.is_locked) {
                                badges.push(
                                  <span key="lock" className="inline-flex items-center gap-0.5 text-[10px] px-2 py-0.5 rounded-full bg-red-100 text-red-700" title={
                                    `アカウントロック中  failed=${L.failed_attempts}  until=${L.locked_until ?? '—'}`
                                  }>
                                    🔒 ロック
                                  </span>,
                                )
                              } else if (L.near_lock) {
                                badges.push(
                                  <span key="nearlock" className="inline-flex items-center gap-0.5 text-[10px] px-2 py-0.5 rounded-full bg-orange-100 text-orange-700" title={
                                    `ログイン失敗 ${L.failed_attempts}/3  あと ${3 - L.failed_attempts} 回でロック`
                                  }>
                                    ⚠ 失敗{L.failed_attempts}
                                  </span>,
                                )
                              }
                              if (L.active_uploads >= 2) {
                                badges.push(
                                  <span key="ul" className="inline-flex items-center gap-0.5 text-[10px] px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700" title="同時アップロード上限 (2/2) 到達">
                                    UL満杯
                                  </span>,
                                )
                              }
                              if (L.exfil_alerted || L.exfil_near_hard_block) {
                                badges.push(
                                  <span key="exfil" className="inline-flex items-center gap-0.5 text-[10px] px-2 py-0.5 rounded-full bg-purple-100 text-purple-700" title={
                                    `exfil  req=${L.exfil_requests}  bytes=${L.exfil_bytes}  alerted=${L.exfil_alerted}  near_block=${L.exfil_near_hard_block}`
                                  }>
                                    EXFIL
                                  </span>,
                                )
                              }
                              return badges.length > 0
                                ? <div className="flex flex-wrap gap-1">{badges}</div>
                                : <span className={`text-xs ${textMuted}`}>—</span>
                            })()}
                          </td>
                          <td className={`px-3 py-2.5 text-xs hidden md:table-cell ${
                            (limits[u.id]?.active_uploads ?? 0) >= 2 ? 'text-red-600 font-semibold' : textMuted
                          }`}>
                            {limits[u.id]?.active_uploads ?? 0}
                          </td>
                          <td className={`px-3 py-2.5 text-xs hidden lg:table-cell ${
                            limits[u.id]?.exfil_alerted ? 'text-amber-600 font-semibold' : textMuted
                          }`}>
                            {limits[u.id]?.exfil_requests ?? 0}
                          </td>
                        </>
                      )}
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2 justify-end">
                          {myRole === 'admin' && limits[u.id]?.is_limited && (
                            <div className="flex items-center gap-1">
                              {limits[u.id]?.is_locked && (
                                <button onClick={() => handleResetLimits(u, 'lock')} disabled={limitResetBusyId === u.id}
                                  title="アカウントロックのみ解除" className={`text-[10px] px-1 rounded border ${border} hover:text-emerald-500 disabled:opacity-50`}>🔒</button>
                              )}
                              {(limits[u.id]?.failed_attempts ?? 0) > 0 && (
                                <button onClick={() => handleResetLimits(u, 'failed_attempts')} disabled={limitResetBusyId === u.id}
                                  title="ログイン失敗カウンタのみ 0 に" className={`text-[10px] px-1 rounded border ${border} hover:text-emerald-500 disabled:opacity-50`}>失敗</button>
                              )}
                              {(limits[u.id]?.active_uploads ?? 0) >= 2 && (
                                <button onClick={() => handleResetLimits(u, 'uploads')} disabled={limitResetBusyId === u.id}
                                  title="進行中アップロードのみ expire" className={`text-[10px] px-1 rounded border ${border} hover:text-emerald-500 disabled:opacity-50`}>UL</button>
                              )}
                              {(limits[u.id]?.exfil_alerted || limits[u.id]?.exfil_near_hard_block) && (
                                <button onClick={() => handleResetLimits(u, 'exfil')} disabled={limitResetBusyId === u.id}
                                  title="EXFIL レート状態のみクリア" className={`text-[10px] px-1 rounded border ${border} hover:text-emerald-500 disabled:opacity-50`}>EX</button>
                              )}
                              <button onClick={() => handleResetLimits(u, 'all')} disabled={limitResetBusyId === u.id}
                                title="全部リセット (確認あり)" className={`${textMuted} hover:text-emerald-500 disabled:opacity-50`}>
                                <RotateCcw size={14} />
                              </button>
                            </div>
                          )}
                          <button
                            onClick={() => openEdit(u)}
                            className={`flex items-center gap-0.5 transition-colors ${
                              editId === u.id ? 'text-blue-500' : `${textMuted} hover:text-blue-500`
                            }`}
                            title={t('users.manage.edit_title')}
                          >
                            <Pencil size={14} />
                            <ChevronDown
                              size={12}
                              className={`transition-transform ${editId === u.id ? 'rotate-180' : ''}`}
                            />
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

                    {/* インライン編集フォーム（行の直下に展開） */}
                    {editId === u.id && (
                      <tr key={`edit-${u.id}`}>
                        <td colSpan={myRole === 'admin' ? 8 : 5} className={`px-4 py-4 border-b ${border} ${isLight ? 'bg-blue-50/60' : 'bg-blue-900/10'}`}>
                          <div className="flex items-center justify-between mb-3">
                            <h3 className={`text-xs font-semibold ${textMain}`}>{t('users.manage.edit_title')}: {u.display_name || u.username}</h3>
                            <button onClick={closeAll} className={`${textMuted} hover:text-red-400`}>
                              <X size={14} />
                            </button>
                          </div>
                          {renderFormFields()}
                        </td>
                      </tr>
                    )}
                  </>
                ))}
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={myRole === 'admin' ? 8 : 5} className={`px-4 py-8 text-center ${textMuted} text-sm`}>
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
