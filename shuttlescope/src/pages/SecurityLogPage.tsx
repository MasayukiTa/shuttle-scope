import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw } from 'lucide-react'
import {
  authRequestLogs, authSecurityEvents,
  RequestLogEntry, SecurityEventEntry,
} from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'

// 外部からの挙動を見る画面 (アプリ内操作の監査ログ = /audit-logs とは分離)。
// request_logs (全 HTTP) と security_events (probe / rate limit 等) の 2 タブ。
type SecTab = 'request' | 'security'

export function SecurityLogPage() {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const { role } = useAuth()
  const [tab, setTab] = useState<SecTab>('security')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [limit, setLimit] = useState(200)

  const [reqRows, setReqRows] = useState<RequestLogEntry[]>([])
  const [secRows, setSecRows] = useState<SecurityEventEntry[]>([])
  // request log フィルタ
  const [reqMethod, setReqMethod] = useState('')
  const [reqPath, setReqPath] = useState('')
  const [reqStatusMin, setReqStatusMin] = useState('')
  const [reqStatusMax, setReqStatusMax] = useState('')
  const [reqIp, setReqIp] = useState('')
  // security event フィルタ
  const [secType, setSecType] = useState('')
  const [secSeverity, setSecSeverity] = useState('')
  const [secIp, setSecIp] = useState('')

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
      if (tab === 'request') {
        const params: { method?: string; path_prefix?: string; status_min?: number; status_max?: number; ip?: string; limit?: number } = { limit }
        if (reqMethod.trim()) params.method = reqMethod.trim().toUpperCase()
        if (reqPath.trim()) params.path_prefix = reqPath.trim()
        const lo = parseInt(reqStatusMin, 10); if (Number.isFinite(lo)) params.status_min = lo
        const hi = parseInt(reqStatusMax, 10); if (Number.isFinite(hi)) params.status_max = hi
        if (reqIp.trim()) params.ip = reqIp.trim()
        const res = await authRequestLogs(params)
        setReqRows(res.data)
      } else {
        const params: { event_type?: string; severity?: string; ip?: string; limit?: number } = { limit }
        if (secType.trim()) params.event_type = secType.trim()
        if (secSeverity.trim()) params.severity = secSeverity.trim()
        if (secIp.trim()) params.ip = secIp.trim()
        const res = await authSecurityEvents(params)
        setSecRows(res.data)
      }
    } catch (err) {
      setError((err as Error).message || 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (role === 'admin') load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, tab])

  if (role !== 'admin') {
    return <div className={`p-6 ${textSecondary}`}>{t('security_log.admin_required', 'admin 権限が必要です')}</div>
  }

  const fmtTs = (ts: string) =>
    new Date(ts).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

  return (
    <div className="p-3 sm:p-6 space-y-4 h-full flex flex-col overflow-hidden">
      <div className="flex-shrink-0">
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('security_log.title', 'セキュリティ監視')}</h1>
        <p className={`text-xs mt-1 ${textMuted}`}>
          {t('security_log.hint', '外部からの HTTP リクエスト・攻撃検知ログ。アプリ内操作の監査は「監査ログ」を参照。')}
        </p>
        <div className="mt-2 flex gap-1 text-xs">
          {([
            ['security', t('security_log.tab_security', 'セキュリティイベント')],
            ['request', t('security_log.tab_request', 'HTTP リクエスト')],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`px-3 py-1 rounded border ${
                tab === k
                  ? (isLight ? 'bg-blue-600 text-white border-blue-600' : 'bg-blue-700 text-white border-blue-700')
                  : (isLight ? 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50' : 'bg-gray-800 border-gray-600 text-gray-200 hover:bg-gray-700')
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 flex-shrink-0">
        {tab === 'request' && <>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>Method</label>
            <select value={reqMethod} onChange={(e) => setReqMethod(e.target.value)} className={inputCls}>
              <option value="">— all —</option>
              <option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
            </select>
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>Path prefix</label>
            <input value={reqPath} onChange={(e) => setReqPath(e.target.value)} className={`${inputCls} w-60`} placeholder="/api/auth/" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>Status ≥</label>
            <input type="number" min={100} max={599} value={reqStatusMin} onChange={(e) => setReqStatusMin(e.target.value)} className={`${inputCls} w-20`} placeholder="400" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>Status ≤</label>
            <input type="number" min={100} max={599} value={reqStatusMax} onChange={(e) => setReqStatusMax(e.target.value)} className={`${inputCls} w-20`} placeholder="599" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>IP</label>
            <input value={reqIp} onChange={(e) => setReqIp(e.target.value)} className={`${inputCls} w-40`} placeholder="192.168. or full" />
          </div>
        </>}
        {tab === 'security' && <>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>Event type</label>
            <select value={secType} onChange={(e) => setSecType(e.target.value)} className={inputCls}>
              <option value="">— all —</option>
              <option>probe_attempt</option>
              <option>nginx_probe_block</option>
              <option>nginx_rate_limit</option>
              <option>rate_limit_hit</option>
              <option>honeytoken_hit</option>
              <option>path_normalization_block</option>
              <option>ip_banned</option>
            </select>
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>Severity</label>
            <select value={secSeverity} onChange={(e) => setSecSeverity(e.target.value)} className={inputCls}>
              <option value="">— all —</option>
              <option>info</option><option>warn</option><option>critical</option>
            </select>
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>IP</label>
            <input value={secIp} onChange={(e) => setSecIp(e.target.value)} className={`${inputCls} w-40`} placeholder="192.168. or full" />
          </div>
        </>}
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.limit', '件数')}</label>
          <input type="number" min={1} max={5000} value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(5000, parseInt(e.target.value, 10) || 200)))}
            className={`${inputCls} w-24`} />
        </div>
        <button onClick={load} disabled={loading}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm ${
            isLight ? 'bg-blue-600 text-white hover:bg-blue-500' : 'bg-blue-700 text-white hover:bg-blue-600'
          } disabled:opacity-50`}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          {t('auth.audit_log.refresh', '再読込')}
        </button>
        <span className={`text-xs ${textMuted}`}>表示: {tab === 'request' ? reqRows.length : secRows.length} 件</span>
      </div>

      {error && <div className="text-sm text-red-400 flex-shrink-0">{error}</div>}

      <div className={`flex-1 min-h-0 overflow-auto rounded border ${borderLine} ${cardBg}`}>
        {tab === 'request' ? (
          <table className="min-w-full text-xs">
            <thead className={`sticky top-0 z-10 ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}>
              <tr className={textMuted}>
                <th className="text-left px-2 py-2">ID</th>
                <th className="text-left px-2 py-2">Time</th>
                <th className="text-left px-2 py-2">Method</th>
                <th className="text-left px-2 py-2">Path</th>
                <th className="text-left px-2 py-2">Status</th>
                <th className="text-left px-2 py-2">Dur(ms)</th>
                <th className="text-left px-2 py-2">IP</th>
                <th className="text-left px-2 py-2 hidden md:table-cell">User</th>
                <th className="text-left px-2 py-2 hidden lg:table-cell">UA</th>
                <th className="text-left px-2 py-2 hidden xl:table-cell">Query</th>
              </tr>
            </thead>
            <tbody>
              {reqRows.length === 0 ? (
                <tr><td colSpan={10} className={`px-3 py-6 text-center ${textMuted}`}>{t('auth.audit_log.empty', 'データなし')}</td></tr>
              ) : reqRows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine}`}>
                  <td className={`px-2 py-1.5 font-mono ${textMuted}`}>{r.id}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${textSecondary}`} title={r.ts}>{fmtTs(r.ts)}</td>
                  <td className={`px-2 py-1.5 font-mono ${textHeading}`}>{r.method}</td>
                  <td className={`px-2 py-1.5 font-mono break-all ${textSecondary}`}>{r.path}</td>
                  <td className={`px-2 py-1.5 font-mono ${r.status >= 500 ? 'text-red-500' : r.status >= 400 ? 'text-amber-500' : textSecondary}`}>{r.status}</td>
                  <td className={`px-2 py-1.5 font-mono ${textMuted}`}>{r.duration_ms}</td>
                  <td className={`px-2 py-1.5 font-mono whitespace-nowrap ${textSecondary}`}>{r.ip_addr || '—'}{r.country ? ` (${r.country})` : ''}</td>
                  <td className={`px-2 py-1.5 hidden md:table-cell ${textSecondary}`}>{r.user_id ?? '—'}</td>
                  <td className={`px-2 py-1.5 hidden lg:table-cell font-mono text-[10px] break-all max-w-[260px] ${textMuted}`}>{r.ua || ''}</td>
                  <td className={`px-2 py-1.5 hidden xl:table-cell font-mono text-[10px] break-all max-w-[300px] ${textMuted}`}>{r.query || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="min-w-full text-xs">
            <thead className={`sticky top-0 z-10 ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}>
              <tr className={textMuted}>
                <th className="text-left px-2 py-2">ID</th>
                <th className="text-left px-2 py-2">Time</th>
                <th className="text-left px-2 py-2">Event</th>
                <th className="text-left px-2 py-2">Sev</th>
                <th className="text-left px-2 py-2">IP</th>
                <th className="text-left px-2 py-2">Path</th>
                <th className="text-left px-2 py-2 hidden md:table-cell">Method</th>
                <th className="text-left px-2 py-2 hidden lg:table-cell">Details</th>
              </tr>
            </thead>
            <tbody>
              {secRows.length === 0 ? (
                <tr><td colSpan={8} className={`px-3 py-6 text-center ${textMuted}`}>{t('auth.audit_log.empty', 'データなし')}</td></tr>
              ) : secRows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine}`}>
                  <td className={`px-2 py-1.5 font-mono ${textMuted}`}>{r.id}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${textSecondary}`} title={r.ts}>{fmtTs(r.ts)}</td>
                  <td className={`px-2 py-1.5 font-mono ${textHeading}`}>{r.event_type}</td>
                  <td className={`px-2 py-1.5 font-mono ${r.severity === 'critical' ? 'text-red-500' : r.severity === 'warn' ? 'text-amber-500' : textSecondary}`}>{r.severity}</td>
                  <td className={`px-2 py-1.5 font-mono whitespace-nowrap ${textSecondary}`}>{r.ip_addr || '—'}</td>
                  <td className={`px-2 py-1.5 font-mono break-all ${textSecondary}`}>{r.path || '—'}</td>
                  <td className={`px-2 py-1.5 hidden md:table-cell font-mono ${textMuted}`}>{r.method || '—'}</td>
                  <td className={`px-2 py-1.5 hidden lg:table-cell font-mono text-[10px] break-all max-w-md ${textMuted}`}>{r.details || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
