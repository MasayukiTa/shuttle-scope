import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, ArrowUp, ArrowDown, Download } from 'lucide-react'
import { authAuditLogs, authAuditLogActions, AuditLogEntry, AuditLogActionItem } from '@/api/client'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'

type SortKey = 'created_at' | 'action' | 'user' | 'ip_addr'
type SortDir = 'asc' | 'desc'

export function AuditLogPage() {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const { role } = useAuth()
  const [rows, setRows] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionFilter, setActionFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [ipFilter, setIpFilter] = useState('')
  const [limit, setLimit] = useState(500)
  // action 名一覧 (dropdown 用)。backend で count desc に並べたものをそのまま表示。
  const [actionOptions, setActionOptions] = useState<AuditLogActionItem[]>([])
  // ソート状態
  const [sortKey, setSortKey] = useState<SortKey>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

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
      const params: { action?: string; user_id?: number; ip?: string; limit?: number } = { limit }
      if (actionFilter.trim()) params.action = actionFilter.trim()
      const uid = parseInt(userFilter, 10)
      if (Number.isFinite(uid) && uid > 0) params.user_id = uid
      if (ipFilter.trim()) params.ip = ipFilter.trim()
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
      // action dropdown 用に distinct action 一覧を取得
      authAuditLogActions()
        .then((r) => setActionOptions(r.data || []))
        .catch(() => { /* 失敗時は dropdown 空のまま、free text 入力で動く */ })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role])

  const sortedRows = useMemo(() => {
    const copy = [...rows]
    const dir = sortDir === 'asc' ? 1 : -1
    copy.sort((a, b) => {
      const get = (r: AuditLogEntry): string | number => {
        switch (sortKey) {
          case 'created_at':
            return r.created_at || ''
          case 'action':
            return r.action || ''
          case 'user':
            return r.username || (r.user_id ? `#${r.user_id}` : '')
          case 'ip_addr':
            return r.ip_addr || ''
        }
      }
      const av = get(a)
      const bv = get(b)
      if (av < bv) return -1 * dir
      if (av > bv) return 1 * dir
      return 0
    })
    return copy
  }, [rows, sortKey, sortDir])

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'created_at' ? 'desc' : 'asc')
    }
  }

  const exportCsv = () => {
    const header = ['id', 'created_at', 'action', 'user_id', 'username', 'ip_addr', 'details']
    const escape = (v: unknown): string => {
      const s = v == null ? '' : String(v)
      if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return '"' + s.replace(/"/g, '""') + '"'
      }
      return s
    }
    const lines = [header.join(',')]
    for (const r of sortedRows) {
      lines.push(
        [
          r.id,
          r.created_at,
          r.action,
          r.user_id ?? '',
          r.username ?? '',
          r.ip_addr ?? '',
          r.details ?? '',
        ]
          .map(escape)
          .join(',')
      )
    }
    const csv = '﻿' + lines.join('\r\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    a.href = url
    a.download = `audit_logs_${ts}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  if (role !== 'admin') {
    return (
      <div className={`p-6 ${textSecondary}`}>admin 権限が必要です</div>
    )
  }

  const sortIcon = (key: SortKey) => {
    if (sortKey !== key) return <span className="opacity-30">↕</span>
    return sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
  }

  return (
    <div className="p-3 sm:p-6 space-y-4 h-full flex flex-col overflow-hidden">
      <div className="flex-shrink-0">
        <h1 className={`text-xl font-semibold ${textHeading}`}>{t('auth.audit_log.title')}</h1>
        <p className={`text-xs mt-1 ${textMuted}`}>{t('auth.audit_log.hint')}</p>
      </div>

      <div className="flex flex-wrap items-end gap-3 flex-shrink-0">
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.filter_action')}</label>
          {/* dropdown: distinct action 一覧。空 = フィルタなし。typo 防止と
             どの action が存在するかの可視化を兼ねる。dropdown 不可時の保険として
             /audit-logs/actions が失敗したら空配列のまま (action filter 無効化)。 */}
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className={`${inputCls} min-w-[180px]`}
          >
            <option value="">— すべて —</option>
            {actionOptions.map((o) => (
              <option key={o.action} value={o.action}>
                {o.action} ({o.count})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.filter_user')}</label>
          <input
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className={inputCls}
            placeholder="数値 user_id (例: 123)"
            inputMode="numeric"
          />
        </div>
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.filter_ip', 'IP')}</label>
          {/* 部分一致 (LIKE %ip%)。"192.168." のような prefix も "203.0.113.5" の
              ような完全 IP も同じ入力欄で扱える。空欄でフィルタなし。 */}
          <input
            value={ipFilter}
            onChange={(e) => setIpFilter(e.target.value)}
            className={`${inputCls} w-40`}
            placeholder={t('auth.audit_log.filter_ip_placeholder', 'e.g. 192.168. or 203.0.113.5')}
            inputMode="text"
          />
        </div>
        <div>
          <label className={`block text-xs mb-1 ${textMuted}`}>{t('auth.audit_log.limit')}</label>
          {/* backend cap は 5000。それ以上入力しても backend で clamp される */}
          <input
            type="number"
            min={1}
            max={5000}
            value={limit}
            onChange={(e) => setLimit(Math.max(1, Math.min(5000, parseInt(e.target.value, 10) || 500)))}
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
        <button
          onClick={exportCsv}
          disabled={loading || rows.length === 0}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm ${
            isLight ? 'bg-emerald-600 text-white hover:bg-emerald-500' : 'bg-emerald-700 text-white hover:bg-emerald-600'
          } disabled:opacity-50`}
          title="現在の表示順で CSV ダウンロード"
        >
          <Download size={14} /> CSV
        </button>
        <span className={`text-xs ${textMuted}`}>表示: {sortedRows.length} 件</span>
      </div>

      {error && <div className="text-sm text-red-400 flex-shrink-0">{error}</div>}

      {/* 縦スクロール領域：list を flex-1 にして残りスペースをすべて使い切る */}
      <div className={`flex-1 min-h-0 overflow-auto rounded border ${borderLine} ${cardBg}`}>
        <table className="min-w-full text-sm">
          <thead className={`sticky top-0 z-10 ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}>
            <tr className={textMuted}>
              <th
                className="text-left px-3 py-2 cursor-pointer select-none"
                onClick={() => handleSort('created_at')}
              >
                <span className="inline-flex items-center gap-1">
                  {t('auth.audit_log.column_time')} {sortIcon('created_at')}
                </span>
              </th>
              <th
                className="text-left px-3 py-2 cursor-pointer select-none"
                onClick={() => handleSort('action')}
              >
                <span className="inline-flex items-center gap-1">
                  {t('auth.audit_log.column_action')} {sortIcon('action')}
                </span>
              </th>
              <th
                className="text-left px-3 py-2 cursor-pointer select-none"
                onClick={() => handleSort('user')}
              >
                <span className="inline-flex items-center gap-1">
                  {t('auth.audit_log.column_user')} {sortIcon('user')}
                </span>
              </th>
              <th
                className="text-left px-3 py-2 cursor-pointer select-none hidden md:table-cell"
                onClick={() => handleSort('ip_addr')}
              >
                <span className="inline-flex items-center gap-1">
                  {t('auth.audit_log.column_ip')} {sortIcon('ip_addr')}
                </span>
              </th>
              <th className="text-left px-3 py-2 hidden lg:table-cell">{t('auth.audit_log.column_details')}</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 ? (
              <tr>
                <td colSpan={5} className={`px-3 py-6 text-center ${textMuted}`}>
                  {t('auth.audit_log.empty')}
                </td>
              </tr>
            ) : (
              sortedRows.map((r) => (
                <tr key={r.id} className={`border-t ${borderLine}`}>
                  <td className={`px-3 py-2 whitespace-nowrap ${textSecondary}`} title={r.created_at}>
                    {(() => {
                      // backend は UTC+Z を返す。JST (Asia/Tokyo) で表示する
                      try {
                        const d = new Date(r.created_at)
                        if (!isNaN(d.getTime())) {
                          return d.toLocaleString('ja-JP', {
                            timeZone: 'Asia/Tokyo',
                            year: 'numeric', month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit', second: '2-digit',
                            hour12: false,
                          })
                        }
                      } catch { /* fall through */ }
                      return r.created_at.replace('T', ' ').slice(0, 19)
                    })()}
                  </td>
                  <td className={`px-3 py-2 whitespace-nowrap ${textHeading}`}>{r.action}</td>
                  <td className={`px-3 py-2 whitespace-nowrap ${textSecondary}`}>
                    {r.username ? `${r.username} (#${r.user_id})` : (r.user_id ? `#${r.user_id}` : '—')}
                  </td>
                  <td className={`px-3 py-2 whitespace-nowrap hidden md:table-cell ${textSecondary}`}>{r.ip_addr || '—'}</td>
                  <td className={`px-3 py-2 font-mono text-xs hidden lg:table-cell ${textSecondary} break-all max-w-md`}>{r.details || ''}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
