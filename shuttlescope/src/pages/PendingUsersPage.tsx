import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, listTeams, newIdempotencyKey, type TeamDTO } from '@/api/client'
import { errorMessage } from '@/utils/errors'

type AssignableRole = 'player' | 'coach' | 'analyst'

interface PendingUser {
  id: number
  username: string
  email: string | null
  email_verified: boolean
  display_name: string | null
  created_at: string | null
}

interface PendingListResp {
  success: boolean
  data: PendingUser[]
}

export default function PendingUsersPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['pending_users'],
    queryFn: () => apiGet<PendingListResp>('/auth/users/pending'),
    refetchInterval: 30_000,
  })

  // 既存チーム一覧を取得して datalist に使用する
  const { data: teamsData } = useQuery({
    queryKey: ['teams_list'],
    queryFn: () => listTeams(),
  })
  const teams: TeamDTO[] = teamsData?.data ?? []

  return (
    <div className="p-4 max-w-5xl mx-auto bg-[var(--ss-bg-app)] min-h-full">
      <h1 className="text-xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)] mb-2">{t('pendingUsers.title')}</h1>
      <p className="text-sm text-[var(--ss-t2)] mb-4">
        {t('pendingUsers.description')}
      </p>

      {isLoading && <div className="text-sm text-[var(--ss-t2)]">{t('app.loading')}</div>}
      {error && (
        <div className="text-sm rounded-ss-md border px-3 py-2 bg-[var(--ss-danger-bg)] border-[var(--ss-danger-border)] text-[var(--ss-danger-text)]">
          {(error as Error).message}
        </div>
      )}

      {data?.data?.length === 0 && (
        <div className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-6 text-center text-sm text-[var(--ss-t3)]">
          {t('pendingUsers.empty')}
        </div>
      )}

      <div className="space-y-3">
        {data?.data?.map((u) => (
          <PendingUserRow
            key={u.id}
            user={u}
            teams={teams}
            onChange={() => qc.invalidateQueries({ queryKey: ['pending_users'] })}
          />
        ))}
      </div>
    </div>
  )
}

function PendingUserRow({
  user,
  teams,
  onChange,
}: {
  user: PendingUser
  teams: TeamDTO[]
  onChange: () => void
}) {
  const { t } = useTranslation()
  const [role, setRole] = useState<AssignableRole>('player')
  const [teamName, setTeamName] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  // datalist の id は行ごとに一意にする
  const datalistId = useMemo(() => `team-suggestions-${user.id}`, [user.id])

  // Approve ボタンの有効条件: チーム名が入力されているか（チームが不要なロールは将来的に追加可能だが現状全ロールで必須）
  const canApprove = teamName.trim().length > 0

  async function handleApprove() {
    if (submitting) return
    if (!canApprove) {
      setMsg(t('pendingUsers.team_name_required'))
      return
    }
    if (!window.confirm(t('pendingUsers.approve_confirm'))) return
    setSubmitting(true)
    setMsg(null)
    try {
      await apiPost(
        `/auth/users/${user.id}/approve`,
        {
          role,
          team_name: teamName.trim(),
        },
        { 'X-Idempotency-Key': newIdempotencyKey() },
      )
      onChange()
    } catch (err: unknown) {
      setMsg(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReject() {
    if (submitting) return
    if (!window.confirm(t('pendingUsers.reject_confirm'))) return
    setSubmitting(true)
    setMsg(null)
    try {
      await apiPost(`/auth/users/${user.id}/reject`, {}, { 'X-Idempotency-Key': newIdempotencyKey() })
      onChange()
    } catch (err: unknown) {
      setMsg(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] shadow-card p-4 space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <div className="font-medium text-sm">{user.username}</div>
          {user.display_name && (
            <div className="text-xs text-[var(--ss-t2)]">{user.display_name}</div>
          )}
          <div className="text-xs text-[var(--ss-t2)]">
            {user.email ?? '(no email)'}
            {user.email_verified ? (
              <span className="ml-2 text-[var(--ss-success)]">{t('auto.PendingUsersPage.verified')}</span>
            ) : (
              <span className="ml-2 text-[var(--ss-warn)]">{t('auto.PendingUsersPage.unverified')}</span>
            )}
          </div>
          <div className="text-[10px] text-[var(--ss-t3)] ss-num">{user.created_at}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-[var(--ss-t3)] mb-1">
            {t('users.manage.role_label')}
          </label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as AssignableRole)}
            className="w-full rounded-ss-md border border-[var(--ss-ctrl-border)] bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] px-2 py-1 text-sm"
          >
            <option value="player">{t('pendingUsers.role.player')}</option>
            <option value="coach">{t('pendingUsers.role.coach')}</option>
            <option value="analyst">{t('pendingUsers.role.analyst')}</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-[var(--ss-t3)] mb-1">
            {t('pendingUsers.team_name_label')}
          </label>
          {/* datalist で既存チーム名をサジェスト。自由入力も可能（新規チーム作成） */}
          <input
            type="text"
            list={datalistId}
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            placeholder={t('pendingUsers.team_name_placeholder')}
            className="w-full rounded-ss-md border border-[var(--ss-ctrl-border)] bg-[var(--ss-ctrl-bg)] text-[var(--ss-ctrl-text)] px-2 py-1 text-sm"
          />
          <datalist id={datalistId}>
            {teams.map((tm) => (
              <option key={tm.id} value={tm.name}>
                {tm.is_independent ? `${tm.name} ［無所属］` : tm.name}
              </option>
            ))}
          </datalist>
          <p className="mt-1 text-[10px] text-[var(--ss-t3)]">
            {t('pendingUsers.team_name_hint')}
          </p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <button
          onClick={handleApprove}
          disabled={submitting || !canApprove}
          className="px-3 py-1.5 rounded-ss-md bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white text-sm transition-colors duration-base ease-out disabled:opacity-50"
        >
          {t('pendingUsers.approve')}
        </button>
        <button
          onClick={handleReject}
          disabled={submitting}
          className="px-3 py-1.5 rounded-ss-md border border-[var(--ss-danger-border)] text-[var(--ss-danger-text)] hover:bg-[var(--ss-danger-bg)] text-sm transition-colors duration-base ease-out disabled:opacity-50"
        >
          {t('pendingUsers.reject')}
        </button>
      </div>

      {msg && <div className="text-xs text-[var(--ss-danger-text)]">{msg}</div>}
    </div>
  )
}
