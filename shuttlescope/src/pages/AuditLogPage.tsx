import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw } from 'lucide-react'
import { authAuditLogs, AuditLogEntry } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'

export function AuditLogPage() {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const { role } = useAuth()
  const [rows, setRows] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionFilter, setActionFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [limit, setLimit] = useState(100)

  const textHeading = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const textSecondary = isLight ? 'text-gray-600' : 'text-gray-300'
  const cardBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderLine = isLight ? 'border-gray-200' : 'border-gray-700'
  const inputCls = `${isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-700 border-gray-600 text-white'} border rounded px-2 py-1 text-sm`

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const params: { action?: string; user_id?: number; limit?: number } = { limit }
      if (actionFilter.trim()) params.action = actionFilter.trim()
      const uid = parseInt(userFilter, 10)
      if (Number.isFinite(uid) && uid > 0) params.user_id = uid
      const res = await authAuditLogs(params)
      setRows(res.data)
    } catch (err) {
      const e = err as Error
      setError(e.message || 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (role === 'admin') {
      load()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role])

  if (role !== 'admin') {
    return (
      <div className={`p-6 ${textSecondary}`}>admin 権限が必要です</div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('auth.audit_log.title')}</h1>
        <p className={`text-xs mt-1 ${textMuted}`}>{t('auth.audit_log.hint')}</p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.filter_action')}</label>
          <input
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className={inputCls}
            placeholder="login_failed"
          />
        </div>
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.filter_user')}</label>
          <input
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className={inputCls}
            placeholder="123"
            inputMode="numeric"
          />
        </div>
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.limit')}</label>
          <input
            type="number"
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(500, parseInt(e.target.value, 10) || 100)))}
            className={`${inputCls} w-24`}
          />
        </div>
        <button
          onClick={load}
          disabled={loading}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm ${
            isLight ? 'bg-blue-600 text-white hover:bg-blue-500' : 'bg-blue-700 text-white hover:bg-blue-600'
          } disabled:opacity-50`}
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          {t('auth.audit_log.refresh')}
        </button>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className={`overflow-x-auto rounded border ${borderLine} ${cardBg}`}>
        <table className="min-w-full text-sm">
          <thead>
            <tr className={`${isLight ? 'bg-gray-50' : 'bg-gray-900'} ${textMuted}`}>
              <th className="text-left px-3 py-2">{t('auth.audit_log.column_time')}</th>
              <th className="text-left px-3 py-2">{t('auth.audit_log.column_action')}</th>
              <th className="text-left px-3 py-2">{t('auth.audit_log.column_user')}</th>
              <th className="text-left px-3 py-2">{t('auth.audit_log.column_ip')}</th>
              <th className="text-left px-3 py-2">{t('auth.audit_log.column_details')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className={`px-3 py-6 text-center ${textMuted}`}>
                  {t('auth.audit_log.empty')}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine}`}>
                  <td className={`px-3 py-2 whitespace-nowrap ${textSecondary}`}>{r.created_at.replace('T', ' ').slice(0, 19)}</td>
                  <td className={`px-3 py-2 whitespace-nowrap ${textHeading}`}>{r.action}</td>
                  <td className={`px-3 py-2 whitespace-nowrap ${textSecondary}`}>
                    {r.username ? `${r.username} (#${r.user_id})` : (r.user_id ? `#${r.user_id}` : '—')}
                  </td>
                  <td className={`px-3 py-2 whitespace-nowrap ${textSecondary}`}>{r.ip_addr || '—'}</td>
                  <td className={`px-3 py-2 font-mono text-xs ${textSecondary}`}>{r.details || ''}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
