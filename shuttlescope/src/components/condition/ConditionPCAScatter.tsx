import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'
import { zScore, covMatrix, powerIterationPCA } from '@/utils/stats'

// PCA 2D 散布コンポーネント
// coach / analyst 限定

interface Props {
  playerId: number
  isLight: boolean
}

const CANDIDATE_KEYS: Array<keyof ConditionRecord> = [
  'hooper_sleep',
  'hooper_soreness',
  'hooper_stress',
  'hooper_fatigue',
  'session_rpe',
  'sleep_hours',
  'weight_kg',
  'muscle_mass_kg',
  'body_fat_pct',
]

const MIN_N = 10
const MIN_COLS = 3

// 月 (1..12) を HSL で回すカラースケール
function monthColor(month: number): string {
  const h = ((month - 1) / 12) * 360
  return `hsl(${h}, 70%, 50%)`
}

function monthFromDate(d: string | null | undefined): number | null {
  if (!d) return null
  const dt = new Date(d + 'T00:00:00Z')
  if (Number.isNaN(dt.getTime())) return null
  return dt.getUTCMonth() + 1
}

export function ConditionPCAScatter({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data, isLoading } = useConditions(playerId, { limit: 200 })

  const records: ConditionRecord[] = useMemo(() => {
    const list = Array.isArray(data) ? [...data] : []
    list.sort((a, b) => (a.measured_at ?? '').localeCompare(b.measured_at ?? ''))
    return list
  }, [data])

  const pca = useMemo(() => {
    // 有効列抽出
    const usableKeys = CANDIDATE_KEYS.filter((k) =>
      records.some((r) => {
        const v = r[k] as unknown
        return typeof v === 'number' && Number.isFinite(v)
      }),
    )
    if (usableKeys.length < MIN_COLS) {
      return { ok: false as const, reason: 'cols', usableKeys, points: [] as PCAPoint[] }
    }
    // 全列で値がある行のみ
    const rows: { rec: ConditionRecord; vals: number[] }[] = []
    for (const r of records) {
      const vals: number[] = []
      let ok = true
      for (const k of usableKeys) {
        const v = r[k] as unknown
        if (typeof v !== 'number' || !Number.isFinite(v)) {
          ok = false
          break
        }
        vals.push(v)
      }
      if (ok) rows.push({ rec: r, vals })
    }
    if (rows.length < MIN_N) {
      return { ok: false as const, reason: 'rows', usableKeys, points: [] as PCAPoint[] }
    }
    // 列ごとの z-score 標準化
    const p = usableKeys.length
    const cols: number[][] = Array.from({ length: p }, () => [])
    for (const row of rows) for (let j = 0; j < p; j++) cols[j].push(row.vals[j])
    const zCols = cols.map((c) => zScore(c))
    // matrix[row][col]
    const matrix: number[][] = rows.map((_, i) => zCols.map((zc) => zc[i]))
    const cov = covMatrix(matrix)
    const { vectors, values } = powerIterationPCA(cov, 2)
    if (vectors.length < 2) {
      return { ok: false as const, reason: 'cols', usableKeys, points: [] as PCAPoint[] }
    }
    const [v1, v2] = vectors
    const totalVar = values.reduce((s, v) => s + Math.max(0, v), 0) || 1
    // 全分散は diag(cov) の和で計算（z-score なのでほぼ p）
    let totalAll = 0
    for (let i = 0; i < p; i++) totalAll += cov[i][i]
    if (totalAll <= 0) totalAll = totalVar
    const ev1 = values[0] / totalAll
    const ev2 = values[1] / totalAll

    // 投影
    const points: PCAPoint[] = matrix.map((row, i) => {
      let pc1 = 0
      let pc2 = 0
      for (let j = 0; j < p; j++) {
        pc1 += row[j] * v1[j]
        pc2 += row[j] * v2[j]
      }
      const rec = rows[i].rec
      const mon = monthFromDate(rec.measured_at) ?? 1
      // 主要寄与因子（絶対値上位2つ）
      const contrib = usableKeys.map((k, j) => ({
        key: k as string,
        score: Math.abs(row[j] * v1[j]) + Math.abs(row[j] * v2[j]),
      }))
      contrib.sort((a, b) => b.score - a.score)
      const topKeys = contrib.slice(0, 2).map((c) => c.key)
      return {
        pc1,
        pc2,
        date: rec.measured_at ?? '',
        month: mon,
        color: monthColor(mon),
        topKeys,
      }
    })

    // loading 上位（絶対値）
    const loadings1 = usableKeys
      .map((k, j) => ({ key: k as string, load: v1[j] }))
      .sort((a, b) => Math.abs(b.load) - Math.abs(a.load))
    const loadings2 = usableKeys
      .map((k, j) => ({ key: k as string, load: v2[j] }))
      .sort((a, b) => Math.abs(b.load) - Math.abs(a.load))

    return {
      ok: true as const,
      usableKeys,
      points,
      ev1,
      ev2,
      loadings1,
      loadings2,
    }
  }, [records])

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']} fallback={null}>
      <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-sm font-semibold">{t('condition.pca.title')}</h2>
          {pca.ok && (
            <span className={`text-xs font-mono ${textMuted}`}>
              {t('condition.pca.variance_explained')}: PC1 {(pca.ev1 * 100).toFixed(1)}% / PC2{' '}
              {(pca.ev2 * 100).toFixed(1)}%
            </span>
          )}
        </div>
        <p className={`text-xs ${textMuted} mb-3`}>{t('condition.pca.description')}</p>

        {isLoading ? (
          <div className={`${textMuted} text-xs`}>…</div>
        ) : !pca.ok ? (
          <div className={`${textMuted} text-xs`}>{t('condition.pca.no_data')}</div>
        ) : (
          <>
            <div style={{ width: '100%', height: 320 }}>
              <ResponsiveContainer>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={isLight ? '#e5e7eb' : '#374151'}
                  />
                  <XAxis
                    type="number"
                    dataKey="pc1"
                    name={t('condition.pca.pc1')}
                    tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 11 }}
                    label={{
                      value: t('condition.pca.pc1'),
                      position: 'insideBottom',
                      offset: -4,
                      fill: isLight ? '#374151' : '#9ca3af',
                      fontSize: 11,
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="pc2"
                    name={t('condition.pca.pc2')}
                    tick={{ fill: isLight ? '#374151' : '#9ca3af', fontSize: 11 }}
                    label={{
                      value: t('condition.pca.pc2'),
                      angle: -90,
                      position: 'insideLeft',
                      fill: isLight ? '#374151' : '#9ca3af',
                      fontSize: 11,
                    }}
                  />
                  <ZAxis range={[40, 40]} />
                  <ReferenceLine x={0} stroke={isLight ? '#9ca3af' : '#6b7280'} />
                  <ReferenceLine y={0} stroke={isLight ? '#9ca3af' : '#6b7280'} />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    contentStyle={{
                      backgroundColor: isLight ? '#ffffff' : '#1f2937',
                      border: `1px solid ${isLight ? '#e5e7eb' : '#374151'}`,
                      fontSize: 12,
                    }}
                    formatter={(_v: unknown, _n: unknown, entry: { payload?: PCAPoint }) => {
                      const p = entry?.payload
                      if (!p) return ['', '']
                      const top = p.topKeys
                        .map((k) => t(`condition.pca.metric.${k}`))
                        .join(', ')
                      return [
                        `PC1=${p.pc1.toFixed(2)}, PC2=${p.pc2.toFixed(2)} / ${t('condition.pca.tooltip_top')}: ${top}`,
                        t('condition.pca.tooltip_date'),
                      ]
                    }}
                    labelFormatter={() => ''}
                  />
                  <Scatter data={pca.points} fill="#3b82f6">
                    {pca.points.map((p, i) => (
                      <Cell key={i} fill={p.color} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className={`mt-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs ${textMuted}`}>
              <div>
                <span className="font-semibold">
                  {t('condition.pca.pc1')} {t('condition.pca.top_loadings')}:
                </span>{' '}
                <span className="font-mono">
                  {pca.loadings1
                    .slice(0, 3)
                    .map(
                      (l) =>
                        `${t(`condition.pca.metric.${l.key}`)}(${l.load.toFixed(2)})`,
                    )
                    .join(', ')}
                </span>
              </div>
              <div>
                <span className="font-semibold">
                  {t('condition.pca.pc2')} {t('condition.pca.top_loadings')}:
                </span>{' '}
                <span className="font-mono">
                  {pca.loadings2
                    .slice(0, 3)
                    .map(
                      (l) =>
                        `${t(`condition.pca.metric.${l.key}`)}(${l.load.toFixed(2)})`,
                    )
                    .join(', ')}
                </span>
              </div>
            </div>
          </>
        )}
      </section>
    </RoleGuard>
  )
}

interface PCAPoint {
  pc1: number
  pc2: number
  date: string
  month: number
  color: string
  topKeys: string[]
}

export default ConditionPCAScatter
