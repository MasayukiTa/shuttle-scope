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
import { useEffect, useState } from 'react'
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
  const [overview, setOverview] = useState<Overview | null>(null)
  const [funnel, setFunnel] = useState<FunnelData | null>(null)
  const [dwell, setDwell] = useState<DwellItem[]>([])
  const [learning, setLearning] = useState<LearningSeries>({})
  const [condition, setCondition] = useState<ConditionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [days, setDays] = useState(30)

  const reload = async () => {
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
  }

  useEffect(() => { void reload() /* eslint-disable-next-line */ }, [days])

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 inline-flex items-center gap-2">
          <MIcon name="analytics" size={26} />
          Product Analytics
        </h1>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-gray-600 dark:text-gray-300">期間:</label>
          <select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value, 10))}
            className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          >
            <option value={7}>7 日</option>
            <option value={30}>30 日</option>
            <option value={90}>90 日</option>
            <option value={365}>365 日</option>
          </select>
          <button
            onClick={() => void reload()}
            className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white inline-flex items-center gap-1"
          >
            <MIcon name="refresh" size={16} /> 再集計
          </button>
        </div>
      </header>

      {err && (
        <div className="text-sm text-red-600 dark:text-red-400 border border-red-200 dark:border-red-700/50 rounded p-3">
          {err}
        </div>
      )}
      {loading && !overview && <div className="text-gray-600 dark:text-gray-300">読み込み中…</div>}

      {/* A. 生存 */}
      {overview && (
        <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-3">A. 生存 (Retention)</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="WAU (7d)" value={overview.wau} />
            <Stat label="MAU (30d)" value={overview.mau} />
            <Stat label="イベント数 (7d)" value={overview.total_events_7d} />
            <Stat label="集計時刻" value={new Date(overview.as_of).toLocaleString('ja-JP')} small />
          </div>
          <div className="mt-4 grid sm:grid-cols-2 gap-4">
            <Kv title="WAU × role" data={overview.wau_by_role} />
            <Kv title="WAU × platform" data={overview.wau_by_platform} />
          </div>
        </section>
      )}

      {/* B. ファネル */}
      {funnel && (
        <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-3">
            B. アノテーション完遂ファネル ({funnel.days}d)
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-gray-600 dark:text-gray-300">
                <tr>
                  <th className="text-left py-1">platform / pass</th>
                  <th className="text-right">開始</th>
                  <th className="text-right">完了</th>
                  <th className="text-right">離脱</th>
                  <th className="text-right">完遂率</th>
                  <th className="text-right">UU</th>
                </tr>
              </thead>
              <tbody className="text-gray-900 dark:text-gray-100">
                {Object.entries(funnel.funnel).flatMap(([plat, passes]) =>
                  Object.entries(passes).sort(([a], [b]) => a.localeCompare(b)).map(([pass, v]) => (
                    <tr key={`${plat}-${pass}`} className="border-t border-gray-200 dark:border-gray-700">
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
            <div className="text-xs text-gray-600 dark:text-gray-300 mb-1">離脱直前 last_input_type Top:</div>
            <div className="flex flex-wrap gap-1">
              {funnel.abandonment_last_input_top.map((x) => (
                <span
                  key={x.last_input_type}
                  className="text-xs px-2 py-1 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-200"
                >
                  {x.last_input_type} × {x.count}
                </span>
              ))}
              {funnel.abandonment_last_input_top.length === 0 && (
                <span className="text-xs text-gray-500">データなし</span>
              )}
            </div>
          </div>
        </section>
      )}

      {/* C. 機能の実需 */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-3">
          C. 機能の実需 (analysis_dwell)
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-gray-600 dark:text-gray-300">
              <tr>
                <th className="text-left">view_id</th>
                <th className="text-right">表示回数</th>
                <th className="text-right">UU</th>
                <th className="text-right">平均滞在</th>
                <th className="text-right">合計滞在 (分)</th>
              </tr>
            </thead>
            <tbody className="text-gray-900 dark:text-gray-100">
              {dwell.map((d) => (
                <tr key={d.view_id} className="border-t border-gray-200 dark:border-gray-700">
                  <td className="py-1">{d.view_id}</td>
                  <td className="text-right">{d.view_count}</td>
                  <td className="text-right">{d.unique_users}</td>
                  <td className="text-right">{Math.round(d.avg_dwell_ms / 1000)}s</td>
                  <td className="text-right">{d.total_dwell_minutes}</td>
                </tr>
              ))}
              {dwell.length === 0 && (
                <tr><td colSpan={5} className="py-2 text-center text-gray-500">データなし</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* D. 学習曲線 */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-3">
          D. 学習曲線 (週次 median time-per-input)
        </h2>
        <div className="overflow-x-auto text-xs">
          {Object.entries(learning).slice(0, 30).map(([uid, series]) => (
            <div key={uid} className="mb-2">
              <div className="font-mono text-gray-700 dark:text-gray-300">user…{uid}</div>
              <div className="flex flex-wrap gap-1">
                {series.map((s) => (
                  <span key={s.week} className="px-2 py-1 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200">
                    {s.week.slice(0, 10)}: {Math.round(s.avg_input_ms / 100) / 10}s (n={s.sample})
                  </span>
                ))}
              </div>
            </div>
          ))}
          {Object.keys(learning).length === 0 && (
            <div className="text-gray-500">データなし</div>
          )}
        </div>
      </section>

      {/* E. 体調入力品質 */}
      <section className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 mb-3">
          E. 体調入力品質 (avg time / 変更回数)
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-gray-600 dark:text-gray-300">
              <tr>
                <th className="text-left">question_id</th>
                <th className="text-right">n</th>
                <th className="text-right">avg time</th>
                <th className="text-right">avg 変更回数</th>
              </tr>
            </thead>
            <tbody className="text-gray-900 dark:text-gray-100">
              {condition.map((c) => (
                <tr key={c.question_id} className="border-t border-gray-200 dark:border-gray-700">
                  <td className="py-1">{c.question_id}</td>
                  <td className="text-right">{c.n}</td>
                  <td className="text-right">{(c.avg_ms / 1000).toFixed(1)}s</td>
                  <td className="text-right">{c.avg_changes.toFixed(2)}</td>
                </tr>
              ))}
              {condition.length === 0 && (
                <tr><td colSpan={4} className="py-2 text-center text-gray-500">データなし</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-xs text-gray-500 dark:text-gray-400">
        本ページのデータは PRIVACY.md §IX-bis に基づく仮名化テレメトリから生成されています。
        個人特定可能な raw user_id は保持していません (HMAC-SHA256 hash のみ)。
      </p>
    </div>
  )
}

function Stat({ label, value, small }: { label: string; value: number | string; small?: boolean }) {
  return (
    <div className="rounded border border-gray-200 dark:border-gray-700 p-3 bg-gray-50 dark:bg-gray-900/40">
      <div className="text-xs text-gray-600 dark:text-gray-400">{label}</div>
      <div className={`font-semibold text-gray-900 dark:text-gray-100 ${small ? 'text-sm' : 'text-2xl'}`}>{value}</div>
    </div>
  )
}

function Kv({ title, data }: { title: string; data: Record<string, number> }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0)
  return (
    <div>
      <div className="text-xs text-gray-600 dark:text-gray-400 mb-1">{title}</div>
      <div className="space-y-1">
        {Object.entries(data).sort(([, a], [, b]) => b - a).map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-sm">
            <span className="w-24 text-gray-700 dark:text-gray-300 truncate">{k}</span>
            <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded h-2 overflow-hidden">
              <div
                className="h-full bg-blue-500"
                style={{ width: total > 0 ? `${(v / total) * 100}%` : '0%' }}
              />
            </div>
            <span className="w-10 text-right text-gray-900 dark:text-gray-100">{v}</span>
          </div>
        ))}
        {Object.keys(data).length === 0 && (
          <div className="text-xs text-gray-500">データなし</div>
        )}
      </div>
    </div>
  )
}
