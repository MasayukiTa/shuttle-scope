import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  authRequestLogs, authSecurityEvents, authErrorLogs, authAuditLogStatus,
  RequestLogEntry, SecurityEventEntry, ErrorLogEntry, AuditLogStatus,
} from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'
import { securityEventLabel, severityLabel } from '@/utils/adminLabels'
import { auditEmptyReason } from '@/utils/auditLogStatus'

// 外部からの挙動を見る画面 (アプリ内操作の監査ログ = /audit-logs とは分離)。
// security_events / request_logs / error_logs の 3 タブ。
type SecTab = 'request' | 'security' | 'error'

// 絞り込みに出すコード (表示名は security_log.event_names / security_log.severity)
const SECURITY_EVENT_CODES = [
  'probe_attempt',
  'nginx_probe_block',
  'nginx_rate_limit',
  'rate_limit_hit',
  'honeytoken_hit',
  'path_normalization_block',
  'ip_banned',
] as const
const SEVERITY_CODES = ['info', 'warn', 'critical'] as const

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
  const [errRows, setErrRows] = useState<ErrorLogEntry[]>([])
  // 各表の記録件数と最新時刻 (一覧が 0 件のとき「未記録」と「絞り込みに合わない」を見分ける)。
  // 取得に失敗したら null のままにして、理由は断定しない。
  const [status, setStatus] = useState<AuditLogStatus | null>(null)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null)
  // error log フィルタ
  const [errExcType, setErrExcType] = useState('')
  const [errPath, setErrPath] = useState('')
  // request log フィルタ
  const [reqMethod, setReqMethod] = useState('')
  const [reqPath, setReqPath] = useState('')
  const [reqStatusMin, setReqStatusMin] = useState('')
  const [reqStatusMax, setReqStatusMax] = useState('')
  const [reqIp, setReqIp] = useState('')
  const [reqSource, setReqSource] = useState('')
  // security event フィルタ
  const [secType, setSecType] = useState('')
  const [secSeverity, setSecSeverity] = useState('')
  const [secIp, setSecIp] = useState('')

  const textHeading = 'text-[var(--ss-t1)]'
  const textMuted = 'text-[var(--ss-t3)]'
  const textSecondary = 'text-[var(--ss-t2)]'
  const cardBg = 'bg-[var(--ss-surface-1)]'
  const borderLine = 'border-[var(--ss-border)]'
  const inputCls = `bg-[var(--ss-surface-1)] border-[var(--ss-border)] text-[var(--ss-t1)] border rounded-ss-md px-2 py-1 text-sm`

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      if (tab === 'request') {
        const params: { method?: string; path_prefix?: string; status_min?: number; status_max?: number; ip?: string; source?: string; limit?: number } = { limit }
        if (reqMethod.trim()) params.method = reqMethod.trim().toUpperCase()
        if (reqPath.trim()) params.path_prefix = reqPath.trim()
        const lo = parseInt(reqStatusMin, 10); if (Number.isFinite(lo)) params.status_min = lo
        const hi = parseInt(reqStatusMax, 10); if (Number.isFinite(hi)) params.status_max = hi
        if (reqIp.trim()) params.ip = reqIp.trim()
        if (reqSource.trim()) params.source = reqSource.trim()
        const res = await authRequestLogs(params)
        setReqRows(res.data)
      } else if (tab === 'security') {
        const params: { event_type?: string; severity?: string; ip?: string; limit?: number } = { limit }
        if (secType.trim()) params.event_type = secType.trim()
        if (secSeverity.trim()) params.severity = secSeverity.trim()
        if (secIp.trim()) params.ip = secIp.trim()
        const res = await authSecurityEvents(params)
        setSecRows(res.data)
      } else {
        const params: { exc_type?: string; path_prefix?: string; limit?: number } = { limit }
        if (errExcType.trim()) params.exc_type = errExcType.trim()
        if (errPath.trim()) params.path_prefix = errPath.trim()
        const res = await authErrorLogs(params)
        setErrRows(res.data)
      }
      setFetchedAt(new Date())
    } catch (err) {
      setError((err as Error).message || 'error')
    } finally {
      setLoading(false)
    }
    try {
      const st = await authAuditLogStatus()
      setStatus(st.data)
    } catch {
      setStatus(null)
    }
  }

  useEffect(() => {
    if (role === 'admin') load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, tab])

  if (role !== 'admin') {
    return <div className={`p-6 ${textSecondary}`}>{t('security_log.admin_required')}</div>
  }

  const fmtTs = (ts: string) =>
    new Date(ts).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

  // 表ごとの状態。tab の値 (request / security / error) と status のキーは同じ。
  const summary = status ? status[tab] : null
  const emptyText = () => {
    const reason = auditEmptyReason(summary)
    if (reason === 'never_recorded') return t('security_log.empty_never_recorded')
    if (reason === 'filtered') return t('security_log.empty_filtered', { total: summary?.total ?? 0 })
    return t('auth.audit_log.empty')
  }

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
            ['error', t('security_log.tab_error', 'エラー')],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`px-3 py-1 rounded-ss-md border ${
                tab === k
                  ? 'bg-[var(--ss-brand)] text-white border-[var(--ss-brand)]'
                  : 'bg-[var(--ss-surface-1)] border-[var(--ss-border)] text-[var(--ss-t1)]'
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
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.col_method')}</label>
            <select value={reqMethod} onChange={(e) => setReqMethod(e.target.value)} className={inputCls}>
              <option value="">{t('security_log.all')}</option>
              <option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
            </select>
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_path_prefix')}</label>
            <input value={reqPath} onChange={(e) => setReqPath(e.target.value)} className={`${inputCls} w-60`} placeholder="/api/auth/" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_status_min')}</label>
            <input type="number" min={100} max={599} value={reqStatusMin} onChange={(e) => setReqStatusMin(e.target.value)} className={`${inputCls} w-20`} placeholder="400" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_status_max')}</label>
            <input type="number" min={100} max={599} value={reqStatusMax} onChange={(e) => setReqStatusMax(e.target.value)} className={`${inputCls} w-20`} placeholder="599" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>IP</label>
            <input value={reqIp} onChange={(e) => setReqIp(e.target.value)} className={`${inputCls} w-40`} placeholder="192.168. or full" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_source')}</label>
            <select value={reqSource} onChange={(e) => setReqSource(e.target.value)} className={inputCls}>
              <option value="">{t('security_log.all')}</option>
              <option value="nginx">{t('security_log.source_edge')}</option>
              <option value="backend">{t('security_log.source_app')}</option>
            </select>
          </div>
        </>}
        {tab === 'security' && <>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_event_type')}</label>
            <select value={secType} onChange={(e) => setSecType(e.target.value)} className={inputCls}>
              <option value="">{t('security_log.all')}</option>
              {SECURITY_EVENT_CODES.map((code) => (
                <option key={code} value={code}>{securityEventLabel(t, code)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_severity')}</label>
            <select value={secSeverity} onChange={(e) => setSecSeverity(e.target.value)} className={inputCls}>
              <option value="">{t('security_log.all')}</option>
              {SEVERITY_CODES.map((code) => (
                <option key={code} value={code}>{severityLabel(t, code)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>IP</label>
            <input value={secIp} onChange={(e) => setSecIp(e.target.value)} className={`${inputCls} w-40`} placeholder="192.168. or full" />
          </div>
        </>}
        {tab === 'error' && <>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_exception_type')}</label>
            <input value={errExcType} onChange={(e) => setErrExcType(e.target.value)} className={`${inputCls} w-48`} placeholder="ValueError" />
          </div>
          <div>
            <label className={`block text-xs mb-1 ${textMuted}`}>{t('security_log.filter_path_prefix')}</label>
            <input value={errPath} onChange={(e) => setErrPath(e.target.value)} className={`${inputCls} w-60`} placeholder="/api/" />
          </div>
        </>}
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.limit')}</label>
          <input type="number" min={1} max={5000} value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(5000, parseInt(e.target.value, 10) || 200)))}
            className={`${inputCls} w-24`} />
        </div>
        <button onClick={load} disabled={loading}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-ss-md bg-[var(--ss-brand)] text-white hover:bg-[var(--ss-brand-hover)] duration-base ease-out text-sm disabled:opacity-50`}>
          <MIcon name="refresh" size={14} className={loading ? 'animate-spin' : ''} />
          {t('auth.audit_log.refresh')}
        </button>
        <span className={`text-xs ${textMuted}`}>{t('security_log.shown_count', { n: tab === 'request' ? reqRows.length : tab === 'security' ? secRows.length : errRows.length })}</span>
      </div>

      <p className={`text-xs flex-shrink-0 ${textMuted}`} data-testid="security-log-status">
        {summary
          ? t('security_log.status_line', {
              total: summary.total,
              latest: summary.latest_ts ? fmtTs(summary.latest_ts) : t('security_log.status_none_yet'),
              fetched: fetchedAt ? fetchedAt.toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour12: false }) : '—',
            })
          : t('security_log.status_unavailable')}
      </p>

      {error && <div className="text-sm text-[var(--ss-danger-text)] flex-shrink-0">{error}</div>}

      <div className={`flex-1 min-h-0 overflow-auto rounded-ss-lg border ${borderLine} ${cardBg}`}>
        {tab === 'error' ? (
          <table className="min-w-full text-xs">
            <thead className={`sticky top-0 z-10 bg-[var(--ss-surface-2)]`}>
              <tr className={textMuted}>
                <th className="text-left px-2 py-2">ID</th>
                <th className="text-left px-2 py-2">{t('security_log.col_time')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_exception')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_method')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_path')}</th>
                <th className="text-left px-2 py-2 hidden md:table-cell">{t('security_log.col_message')}</th>
                <th className="text-left px-2 py-2 hidden lg:table-cell">{t('security_log.col_request_id')}</th>
              </tr>
            </thead>
            <tbody>
              {errRows.length === 0 ? (
                <tr><td colSpan={7} className={`px-3 py-6 text-center ${textMuted}`}>{emptyText()}</td></tr>
              ) : errRows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine} align-top`}>
                  <td className={`px-2 py-1.5 font-mono ${textMuted}`}>{r.id}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${textSecondary}`} title={r.ts}>{fmtTs(r.ts)}</td>
                  <td className={`px-2 py-1.5 font-mono text-[var(--ss-danger-text)]`}>{r.exc_type || '—'}</td>
                  <td className={`px-2 py-1.5 font-mono ${textHeading}`}>{r.method || '—'}</td>
                  <td className={`px-2 py-1.5 font-mono break-all ${textSecondary}`}>{r.path || '—'}</td>
                  <td className={`px-2 py-1.5 hidden md:table-cell font-mono text-[10px] break-all max-w-md ${textMuted}`} title={r.traceback || ''}>{r.message || ''}</td>
                  <td className={`px-2 py-1.5 hidden lg:table-cell font-mono text-[10px] ${textMuted}`}>{r.request_id || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : tab === 'request' ? (
          <table className="min-w-full text-xs">
            <thead className={`sticky top-0 z-10 bg-[var(--ss-surface-2)]`}>
              <tr className={textMuted}>
                <th className="text-left px-2 py-2">ID</th>
                <th className="text-left px-2 py-2">{t('security_log.col_time')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_source')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_method')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_path')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_status')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_duration')}</th>
                <th className="text-left px-2 py-2">IP</th>
                <th className="text-left px-2 py-2 hidden md:table-cell">{t('security_log.col_user')}</th>
                <th className="text-left px-2 py-2 hidden lg:table-cell">UA</th>
                <th className="text-left px-2 py-2 hidden xl:table-cell">{t('security_log.col_query')}</th>
              </tr>
            </thead>
            <tbody>
              {reqRows.length === 0 ? (
                <tr><td colSpan={11} className={`px-3 py-6 text-center ${textMuted}`}>{emptyText()}</td></tr>
              ) : reqRows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine}`}>
                  <td className={`px-2 py-1.5 font-mono ${textMuted}`}>{r.id}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${textSecondary}`} title={r.ts}>{fmtTs(r.ts)}</td>
                  <td className={`px-2 py-1.5 font-mono ${r.source === 'nginx' ? 'text-[var(--ss-brand)]' : textMuted}`}>{r.source || '—'}</td>
                  <td className={`px-2 py-1.5 font-mono ${textHeading}`}>{r.method}</td>
                  <td className={`px-2 py-1.5 font-mono break-all ${textSecondary}`}>{r.path}</td>
                  <td className={`px-2 py-1.5 font-mono ss-num ${r.status >= 500 ? 'text-[var(--ss-danger-text)]' : r.status >= 400 ? 'text-[var(--ss-warning-text)]' : textSecondary}`}>{r.status}</td>
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
            <thead className={`sticky top-0 z-10 bg-[var(--ss-surface-2)]`}>
              <tr className={textMuted}>
                <th className="text-left px-2 py-2">ID</th>
                <th className="text-left px-2 py-2">{t('security_log.col_time')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_event')}</th>
                <th className="text-left px-2 py-2">{t('security_log.col_severity')}</th>
                <th className="text-left px-2 py-2">IP</th>
                <th className="text-left px-2 py-2">{t('security_log.col_path')}</th>
                <th className="text-left px-2 py-2 hidden md:table-cell">{t('security_log.col_method')}</th>
                <th className="text-left px-2 py-2 hidden lg:table-cell">{t('security_log.col_details')}</th>
              </tr>
            </thead>
            <tbody>
              {secRows.length === 0 ? (
                <tr><td colSpan={8} className={`px-3 py-6 text-center ${textMuted}`}>{emptyText()}</td></tr>
              ) : secRows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine}`}>
                  <td className={`px-2 py-1.5 font-mono ${textMuted}`}>{r.id}</td>
                  <td className={`px-2 py-1.5 whitespace-nowrap ${textSecondary}`} title={r.ts}>{fmtTs(r.ts)}</td>
                  <td className={`px-2 py-1.5 ${textHeading}`} title={r.event_type}>{securityEventLabel(t, r.event_type)}</td>
                  <td className={`px-2 py-1.5 font-mono ${r.severity === 'critical' ? 'text-[var(--ss-danger-text)]' : r.severity === 'warn' ? 'text-[var(--ss-warning-text)]' : textSecondary}`}>{severityLabel(t, r.severity)}</td>
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
