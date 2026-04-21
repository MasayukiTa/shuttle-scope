import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import { useConditions, ConditionRecord } from '@/hooks/useConditions'
import { mean, sampleStd } from '@/utils/stats'

// 外れ週検出 (coach / analyst 限定)
// 各週(=各 ConditionRecord) について、自身を除く直近28日ウィンドウを基準に
// Z スコアを算出し、|Z|>=2 をリスト化する。

interface Props {
  playerId: number
  isLight: boolean
}

// 解析対象指標キー (ConditionRecord 上のフィールド名と一致)
const METRIC_KEYS = [
  'ccs',
  'hooper_sleep',
  'hooper_soreness',
  'hooper_stress',
  'hooper_fatigue',
  'session_rpe',
  'sleep_hours',
] as const

type MetricKey = (typeof METRIC_KEYS)[number]

const PRIMARY: MetricKey = 'ccs'

const WINDOW_DAYS = 28
const MIN_SAMPLE = 5
const Z_OUTLIER = 2
const Z_HIGH = 3
const Z_CO_BREAK = 1.5

interface ZRow {
  recordId: number
  date: string
  primaryZ: number | null
  zMap: Partial<Record<MetricKey, number>>
}

interface OutlierRow {
  recordId: number
  date: string
  primaryZ: number
  severity: 'high' | 'medium'
  coBreak: MetricKey[]
  zMap: Partial<Record<MetricKey, number>>
}

function getMetric(rec: ConditionRecord, key: MetricKey): number | null {
  const v = (rec as unknown as Record<string, unknown>)[key]
  if (v == null) return null
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return v
}

function parseDate(s: string | undefined): number | null {
  if (!s) return null
  const t = Date.parse(s)
  return Number.isFinite(t) ? t : null
}

// 当該レコードの日付から見て過去28日 (当該日除く) の値を抽出
function windowValues(
  records: ConditionRecord[],
  targetIdx: number,
  key: MetricKey,
): number[] {
  const target = records[targetIdx]
  const tT = parseDate(target.measured_at)
  if (tT == null) return []
  const lower = tT - WINDOW_DAYS * 24 * 60 * 60 * 1000
  const out: number[] = []
  for (let i = 0; i < records.length; i++) {
    if (i === targetIdx) continue
    const r = records[i]
    const rt = parseDate(r.measured_at)
    if (rt == null) continue
    if (rt < lower || rt >= tT) continue
    const v = getMetric(r, key)
    if (v == null) continue
    out.push(v)
  }
  return out
}

function computeZ(records: ConditionRecord[], idx: number, key: MetricKey): number | null {
  const v = getMetric(records[idx], key)
  if (v == null) return null
  const win = windowValues(records, idx, key)
  if (win.length < MIN_SAMPLE) return null
  const m = mean(win)
  const sd = sampleStd(win)
  if (m == null || sd == null || sd === 0) return null
  return (v - m) / sd
}

export function ConditionOutlierWeeks({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading, error } = useConditions(playerId, { limit: 200 })
  const [openId, setOpenId] = useState<number | null>(null)

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const muted = isLight ? 'text-gray-500' : 'text-gray-400'
  const headBg = isLight ? 'bg-gray-50' : 'bg-gray-900/60'
  const rowHover = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/40'

  const rows = useMemo<OutlierRow[]>(() => {
    const records = (data ?? []).slice()
    if (records.length === 0) return []
    // 日付昇順に並べる (windowValues 内で日付フィルタするので順序は重要ではないが、表示順統一のため)
    records.sort((a, b) => (parseDate(a.measured_at) ?? 0) - (parseDate(b.measured_at) ?? 0))

    const all: ZRow[] = records.map((rec, idx) => {
      const zMap: Partial<Record<MetricKey, number>> = {}
      for (const k of METRIC_KEYS) {
        const z = computeZ(records, idx, k)
        if (z != null) zMap[k] = z
      }
      const primaryZ = zMap[PRIMARY] ?? null
      return { recordId: rec.id, date: rec.measured_at ?? '', primaryZ, zMap }
    })

    const outliers: OutlierRow[] = []
    for (const r of all) {
      if (r.primaryZ == null) continue
      const az = Math.abs(r.primaryZ)
      if (az < Z_OUTLIER) continue
      const severity: OutlierRow['severity'] = az >= Z_HIGH ? 'high' : 'medium'
      const coBreak: MetricKey[] = []
      for (const k of METRIC_KEYS) {
        if (k === PRIMARY) continue
        const z = r.zMap[k]
        if (z == null) continue
        if (Math.abs(z) >= Z_CO_BREAK) coBreak.push(k)
      }
      outliers.push({
        recordId: r.recordId,
        date: r.date,
        primaryZ: r.primaryZ,
        severity,
        coBreak,
        zMap: r.zMap,
      })
    }
    // 新しい順
    outliers.sort((a, b) => (parseDate(b.date) ?? 0) - (parseDate(a.date) ?? 0))
    return outliers
  }, [data])

  function severityClass(sev: OutlierRow['severity']): string {
    if (sev === 'high') return 'bg-red-500/20 text-red-400 border-red-500/40'
    return 'bg-amber-500/20 text-amber-400 border-amber-500/40'
  }

  const openRow = openId == null ? null : rows.find((r) => r.recordId === openId) ?? null

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold">{t('condition.outlier.title')}</h2>
        <span className={`text-[11px] ${muted}`}>{t('condition.outlier.description')}</span>
      </div>

      {isLoading ? (
        <div className={`${muted} text-xs`}>{t('condition.outlier.loading')}</div>
      ) : error ? (
        <div className={`${muted} text-xs`}>{t('condition.outlier.no_data')}</div>
      ) : (data ?? []).length < MIN_SAMPLE + 1 ? (
        <div className={`${muted} text-xs`}>{t('condition.outlier.insufficient')}</div>
      ) : rows.length === 0 ? (
        <div className={`${muted} text-xs`}>{t('condition.outlier.no_data')}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className={headBg}>
              <tr>
                <th className="text-left px-2 py-1 font-medium">{t('condition.outlier.col_date')}</th>
                <th className="text-left px-2 py-1 font-medium">{t('condition.outlier.col_metric_z')}</th>
                <th className="text-left px-2 py-1 font-medium">{t('condition.outlier.col_co_break')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.recordId}
                  onClick={() => setOpenId(r.recordId)}
                  className={`cursor-pointer border-t ${borderColor} ${rowHover}`}
                >
                  <td className="px-2 py-1 align-top">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-mono uppercase ${severityClass(
                          r.severity,
                        )}`}
                      >
                        {t(`condition.outlier.severity.${r.severity}`)}
                      </span>
                      <span>{r.date}</span>
                    </div>
                  </td>
                  <td className="px-2 py-1 align-top font-mono">
                    {r.primaryZ.toFixed(2)}
                    <span className={`ml-1 ${muted}`}>
                      ({t(`condition.outlier.metric.${PRIMARY}`)})
                    </span>
                  </td>
                  <td className="px-2 py-1 align-top">
                    {r.coBreak.length === 0 ? (
                      <span className={muted}>{t('condition.outlier.no_value')}</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {r.coBreak.map((k) => {
                          const z = r.zMap[k]!
                          return (
                            <span
                              key={k}
                              className={`px-1.5 py-0.5 rounded border text-[10px] ${borderColor} ${muted}`}
                            >
                              {t(`condition.outlier.metric.${k}`)}: {z.toFixed(2)}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openRow && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setOpenId(null)}
        >
          <div
            className={`max-w-md w-full rounded-lg border ${borderColor} ${panelBg} p-4 shadow-xl`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">
                {t('condition.outlier.detail_title')} ({openRow.date})
              </h3>
              <button
                type="button"
                onClick={() => setOpenId(null)}
                className={`text-xs px-2 py-0.5 border rounded ${borderColor}`}
              >
                {t('condition.outlier.close')}
              </button>
            </div>
            <table className="w-full text-xs">
              <tbody>
                {METRIC_KEYS.map((k) => {
                  const z = openRow.zMap[k]
                  return (
                    <tr key={k} className={`border-t ${borderColor}`}>
                      <td className="px-2 py-1">{t(`condition.outlier.metric.${k}`)}</td>
                      <td className="px-2 py-1 font-mono text-right">
                        {z == null ? t('condition.outlier.no_value') : z.toFixed(2)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}

export default ConditionOutlierWeeks
