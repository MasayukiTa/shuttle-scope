import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, newIdempotencyKey } from '@/api/client'

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

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <h1 className="text-xl font-bold mb-2">{t('pendingUsers.title')}</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        {t('pendingUsers.description')}
      </p>

      {isLoading && <div className="text-sm">{t('app.loading')}</div>}
      {error && (
        <div className="text-sm text-red-600">{(error as Error).message}</div>
      )}

      {data?.data?.length === 0 && (
        <div className="rounded border border-gray-200 dark:border-gray-700 p-6 text-center text-sm text-gray-500">
          {t('pendingUsers.empty')}
        </div>
      )}

      <div className="space-y-3">
        {data?.data?.map((u) => (
          <PendingUserRow key={u.id} user={u} onChange={() => qc.invalidateQueries({ queryKey: ['pending_users'] })} />
        ))}
      </div>
    </div>
  )
}

function PendingUserRow({ user, onChange }: { user: PendingUser; onChange: () => void }) {
  const { t } = useTranslation()
  const [role, setRole] = useState<'analyst' | 'coach' | 'player'>('player')
  const [teamId, setTeamId] = useState<string>('')
  const [teamName, setTeamName] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  async function handleApprove() {
    if (submitting) return
    if (!window.confirm(t('pendingUsers.approve_confirm'))) return
    setSubmitting(true)
    setMsg(null)
    try {
      await apiPost(`/auth/users/${user.id}/approve`, {
        role,
        team_id: teamId ? Number(teamId) : null,
        team_name: teamName || null,
      }, { 'X-Idempotency-Key': newIdempotencyKey() })
      onChange()
    } catch (err: any) {
      setMsg(err?.message ?? String(err))
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
      await apiPost(`/auth/users/${user.id}/reject`, {},
        { 'X-Idempotency-Key': newIdempotencyKey() })
      onChange()
    } catch (err: any) {
      setMsg(err?.message ?? String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <div className="font-medium text-sm">{user.username}</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            {user.email ?? '(no email)'}
            {user.email_verified ? (
              <span className="ml-2 text-green-600">verified</span>
            ) : (
              <span className="ml-2 text-amber-600">unverified</span>
            )}
          </div>
          <div className="text-[10px] text-gray-400">{user.created_at}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <select value={role} onChange={(e) => setRole(e.target.value as any)}
                className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-sm">
          <option value="player">{t('pendingUsers.role.player')}</option>
          <option value="coach">{t('pendingUsers.role.coach')}</option>
          <option value="analyst">{t('pendingUsers.role.analyst')}</option>
        </select>
        <input type="number" value={teamId} onChange={(e) => setTeamId(e.target.value)}
               placeholder={t('pendingUsers.team_id_placeholder')}
               className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-sm" />
        <input type="text" value={teamName} onChange={(e) => setTeamName(e.target.value)}
               placeholder={t('pendingUsers.team_name_placeholder')}
               className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-sm" />
      </div>

      <div className="flex flex-col sm:flex-row gap-2">
        <button onClick={handleApprove} disabled={submitting}
                className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm disabled:opacity-50">
          {t('pendingUsers.approve')}
        </button>
        <button onClick={handleReject} disabled={submitting}
                className="px-3 py-1.5 rounded border border-red-300 text-red-700 dark:border-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-900/20 text-sm disabled:opacity-50">
          {t('pendingUsers.reject')}
        </button>
      </div>

      {msg && <div className="text-xs text-red-600">{msg}</div>}
    </div>
  )
}
