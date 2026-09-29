/**
 * Admin Analytics — 製品 KPI ダッシュボード。
 *
 * 5 panel:
 *   A. 生存 (WAU/MAU/role-platform)
 *   B. アノテーション完遂ファネル + 離脱直前 last_input_type
 *   C. 機能の実需 (analysis_dwell ランキング)
 *   D. 学習曲線 (per-user time-per-input weekly)
 *   E. 体調入力品質 (question_id 別 input time / 変更回数)
 *
 * すべてリアルタイム集計。重くなれば backend 側で MV 化すれば良い設計。
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'

interface Overview {
  wau: number
  mau: number
  total_events_7d: number
  wau_by_role: Record<string, number>
  wau_by_platform: Record<string, number>
  as_of: string
}

interface FunnelPlatform {
  [pass: string]: { started: number; completed: number; abandoned: number; unique_users_started: number }
}

interface FunnelData {
  funnel: Record<string, FunnelPlatform>
  abandonment_last_input_top: { last_input_type: string; count: number }[]
  days: number
}

interface DwellItem { view_id: string; view_count: number; unique_users: number; avg_dwell_ms: number; total_dwell_minutes: number }
interface LearningSeries { [userKey: string]: { week: string; avg_input_ms: number; sample: number }[] }
interface ConditionItem { question_id: string; n: number; avg_ms: number; avg_changes: number }

export default function AdminAnalyticsPage() {
  const { t } = useTranslation()
  const [overview, setOverview] = useState<Overview | null>(null)
  const [funnel, setFunnel] = useState<FunnelData | null>(null)
  const [dwell, setDwell] = useState<DwellItem[]>([])
  const [learning, setLearning] = useState<LearningSeries>({})
  const [condition, setCondition] = useState<ConditionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [days, setDays] = useState(30)

  const reload = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const [ov, fn, dw, lr, cq] = await Promise.all([
        apiGet<{ data: Overview }>('/admin/analytics/overview'),
        apiGet<{ data: FunnelData }>(`/admin/analytics/funnel?days=${days}`),
        apiGet<{ data: { items: DwellItem[] } }>(`/admin/analytics/dwell?days=${days}&limit=30`),
        apiGet<{ data: { series: LearningSeries } }>('/admin/analytics/learning?weeks=8'),
        apiGet<{ data: { items: ConditionItem[] } }>(`/admin/analytics/condition_quality?days=${days}`),
      ])
      setOverview(ov.data)
      setFunnel(fn.data)
      setDwell(dw.data.items)
      setLearning(lr.data.series)
      setCondition(cq.data.items)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { void reload()   }, [reload])

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-[var(--ss-t1)] inline-flex items-center gap-2">
          <MIcon name="analytics" size={26} />
          Product Analytics
        </h1>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-[var(--ss-t2)]">{t('admin.analytics.period')}</label>
          <select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value, 10))}
            className="px-2 py-1 rounded-ss-md border border-[var(--ss-border)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)]"
          >
            <option value={7}>{t('admin.analytics.days', { count: 7 })}</option>
            <option value={30}>{t('admin.analytics.days', { count: 30 })}</option>
            <option value={90}>{t('admin.analytics.days', { count: 90 })}</option>
            <option value={365}>{t('admin.analytics.days', { count: 365 })}</option>
          </select>
          <button
            onClick={() => void reload()}
            className="px-3 py-1 rounded-ss-md bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white inline-flex items-center gap-1"
          >
            <MIcon name="refresh" size={16} /> {t('admin.analytics.reaggregate')}
          </button>
        </div>
      </header>

      {err && (
        <div className="text-sm text-[var(--ss-danger-text)] border border-[var(--ss-danger-border)] bg-[var(--ss-danger-bg)] rounded-ss-lg p-3">
          {err}
        </div>
      )}
      {loading && !overview && <div className="text-[var(--ss-t2)]">{t('admin.analytics.loading')}</div>}

      {/* A. 生存 */}
      {overview && (
        <section className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-4">
          <h2 className="font-semibold text-[var(--ss-t1)] mb-3">{t('admin.analytics.section_a_title')}</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label={t('admin.analytics.stat_wau')} value={overview.wau} />
            <Stat label={t('admin.analytics.stat_mau')} value={overview.mau} />
            <Stat label={t('admin.analytics.stat_events_7d')} value={overview.total_events_7d} />
            <Stat label={t('admin.analytics.stat_as_of')} value={new Date(overview.as_of).toLocaleString('ja-JP')} small />
          </div>
          <div className="mt-4 grid sm:grid-cols-2 gap-4">
            <Kv title={t('admin.analytics.kv_wau_role')} data={overview.wau_by_role} />
            <Kv title={t('admin.analytics.kv_wau_platform')} data={overview.wau_by_platform} />
          </div>
        </section>
      )}

      {/* B. ファネル */}
      {funnel && (
        <section className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-4">
          <h2 className="font-semibold text-[var(--ss-t1)] mb-3">
            {t('admin.analytics.section_b_title', { days: funnel.days })}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[var(--ss-t2)] bg-[var(--ss-surface-2)]">
                <tr>
                  <th className="text-left py-1">{t('admin.analytics.col_platform_pass')}</th>
                  <th className="text-right">{t('admin.analytics.col_started')}</th>
                  <th className="text-right">{t('admin.analytics.col_completed')}</th>
                  <th className="text-right">{t('admin.analytics.col_abandoned')}</th>
                  <th className="text-right">{t('admin.analytics.col_completion_rate')}</th>
                  <th className="text-right">{t('admin.analytics.col_uu')}</th>
                </tr>
              </thead>
              <tbody className="text-[var(--ss-t1)]">
                {Object.entries(funnel.funnel).flatMap(([plat, passes]) =>
                  Object.entries(passes).sort(([a], [b]) => a.localeCompare(b)).map(([pass, v]) => (
                    <tr key={`${plat}-${pass}`} className="border-t border-[var(--ss-border)]">
                      <td className="py-1">{plat} / {pass}</td>
                      <td className="text-right">{v.started}</td>
                      <td className="text-right">{v.completed}</td>
                      <td className="text-right">{v.abandoned}</td>
                      <td className="text-right">
                        {v.started > 0 ? `${Math.round((v.completed / v.started) * 100)}%` : '—'}
                      </td>
                      <td className="text-right">{v.unique_users_started}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4">
            <div className="text-xs text-[var(--ss-t2)] mb-1">{t('admin.analytics.abandonment_top_label')}</div>
            <div className="flex flex-wrap gap-1">
              {funnel.abandonment_last_input_top.map((x) => (
                <span
                  key={x.last_input_type}
                  className="text-xs px-2 py-1 rounded-ss-sm bg-[var(--ss-warning-bg)] text-[var(--ss-warning-text)]"
                >
                  {x.last_input_type} × {x.count}
                </span>
              ))}
              {funnel.abandonment_last_input_top.length === 0 && (
                <span className="text-xs text-[var(--ss-t3)]">{t('admin.analytics.no_data')}</span>
              )}
            </div>
          </div>
        </section>
      )}

      {/* C. 機能の実需 */}
      <section className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-4">
        <h2 className="font-semibold text-[var(--ss-t1)] mb-3">
          {t('admin.analytics.section_c_title')}
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[var(--ss-t2)] bg-[var(--ss-surface-2)]">
              <tr>
                <th className="text-left">{t('admin.analytics.col_view_id')}</th>
                <th className="text-right">{t('admin.analytics.col_view_count')}</th>
                <th className="text-right">{t('admin.analytics.col_uu')}</th>
                <th className="text-right">{t('admin.analytics.col_avg_dwell')}</th>
                <th className="text-right">{t('admin.analytics.col_total_dwell_min')}</th>
              </tr>
            </thead>
            <tbody className="text-[var(--ss-t1)]">
              {dwell.map((d) => (
                <tr key={d.view_id} className="border-t border-[var(--ss-border)]">
                  <td className="py-1">{d.view_id}</td>
                  <td className="text-right">{d.view_count}</td>
                  <td className="text-right">{d.unique_users}</td>
                  <td className="text-right">{Math.round(d.avg_dwell_ms / 1000)}s</td>
                  <td className="text-right">{d.total_dwell_minutes}</td>
                </tr>
              ))}
              {dwell.length === 0 && (
                <tr><td colSpan={5} className="py-2 text-center text-[var(--ss-t3)]">{t('admin.analytics.no_data')}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* D. 学習曲線 */}
      <section className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-4">
        <h2 className="font-semibold text-[var(--ss-t1)] mb-3">
          {t('admin.analytics.section_d_title')}
        </h2>
        <div className="overflow-x-auto text-xs">
          {Object.entries(learning).slice(0, 30).map(([uid, series]) => (
            <div key={uid} className="mb-2">
              <div className="font-mono text-[var(--ss-t2)]">{t('admin.analytics.user_prefix', { uid })}</div>
              <div className="flex flex-wrap gap-1">
                {series.map((s) => (
                  <span key={s.week} className="px-2 py-1 rounded-ss-sm bg-[var(--ss-brand-tint)] text-[var(--ss-brand)]">
                    {s.week.slice(0, 10)}: {Math.round(s.avg_input_ms / 100) / 10}s (n={s.sample})
                  </span>
                ))}
              </div>
            </div>
          ))}
          {Object.keys(learning).length === 0 && (
            <div className="text-[var(--ss-t3)]">{t('admin.analytics.no_data')}</div>
          )}
        </div>
      </section>

      {/* E. 体調入力品質 */}
      <section className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-4">
        <h2 className="font-semibold text-[var(--ss-t1)] mb-3">
          {t('admin.analytics.section_e_title')}
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[var(--ss-t2)] bg-[var(--ss-surface-2)]">
              <tr>
                <th className="text-left">{t('admin.analytics.col_question_id')}</th>
                <th className="text-right">{t('admin.analytics.col_n')}</th>
                <th className="text-right">{t('admin.analytics.col_avg_time')}</th>
                <th className="text-right">{t('admin.analytics.col_avg_changes')}</th>
              </tr>
            </thead>
            <tbody className="text-[var(--ss-t1)]">
              {condition.map((c) => (
                <tr key={c.question_id} className="border-t border-[var(--ss-border)]">
                  <td className="py-1">{c.question_id}</td>
                  <td className="text-right">{c.n}</td>
                  <td className="text-right">{(c.avg_ms / 1000).toFixed(1)}s</td>
                  <td className="text-right">{c.avg_changes.toFixed(2)}</td>
                </tr>
              ))}
              {condition.length === 0 && (
                <tr><td colSpan={4} className="py-2 text-center text-[var(--ss-t3)]">{t('admin.analytics.no_data')}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-xs text-[var(--ss-t3)]">
        {t('admin.analytics.privacy_note')}
      </p>
    </div>
  )
}

function Stat({ label, value, small }: { label: string; value: number | string; small?: boolean }) {
  return (
    <div className="rounded-ss-lg border border-[var(--ss-border)] p-3 bg-[var(--ss-surface-2)]">
      <div className="text-xs text-[var(--ss-t3)]">{label}</div>
      <div className={`font-semibold text-[var(--ss-t1)] ${small ? 'text-sm' : 'text-2xl'}`}>{value}</div>
    </div>
  )
}

function Kv({ title, data }: { title: string; data: Record<string, number> }) {
  const { t } = useTranslation()
  const total = Object.values(data).reduce((a, b) => a + b, 0)
  return (
    <div>
      <div className="text-xs text-[var(--ss-t3)] mb-1">{title}</div>
      <div className="space-y-1">
        {Object.entries(data).sort(([, a], [, b]) => b - a).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-sm">
            <span className="w-24 text-[var(--ss-t2)] truncate">{k}</span>
            <div className="flex-1 bg-[var(--ss-surface-2)] rounded-ss-sm h-2 overflow-hidden">
              <div
                className="h-full bg-[var(--ss-brand)]"
                style={{ width: total > 0 ? `${(v / total) * 100}%` : '0%' }}
              />
            </div>
            <span className="w-10 text-right ss-num text-[var(--ss-t1)]">{v}</span>
          </div>
        ))}
        {Object.keys(data).length === 0 && (
          <div className="text-xs text-[var(--ss-t3)]">{t('admin.analytics.no_data')}</div>
        )}
      </div>
    </div>
  )
}
