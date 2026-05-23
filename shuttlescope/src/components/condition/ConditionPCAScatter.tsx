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
import { catColor } from '@/styles/categoricalPalette'

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

// 月 (1..12) → 月の四半期グループ × 月内位置の shape で識別 (color × shape combo)。
// 12 色を並べても色弱ユーザは 4〜6 色しか識別できない (deutan で赤/橙/茶/緑/オリーブが
// 混ざる)。Design Language §6.3 ルール 4 に従い、6 を超える categorical は shape と
// 組合せる。
//
// **季節 (春夏秋冬) を意味付けにしない**: 東南アジア (年中夏) / 南半球 (季節逆) で
// 「夏が緑」「冬が青」は誤った意味になるため、**1-3月 / 4-6月 / 7-9月 / 10-12月** の
// 四半期 (Q1〜Q4) を identity の根拠にする。色はカテゴリ識別だけで、季節の symbolism は
// 持たせない。
//   - Q1 (1-3月)   = Cool 青系  × {1:●, 2:■, 3:▲}
//   - Q2 (4-6月)   = Green 青緑 × {4:●, 5:■, 6:▲}
//   - Q3 (7-9月)   = Warm 朱系  × {7:●, 8:■, 9:▲}
//   - Q4 (10-12月) = Amber 橙系 × {10:●, 11:■, 12:▲}
function monthQuarterKey(month: number): 'Cool' | 'Green' | 'Warm' | 'Amber' {
  if (month <= 3) return 'Cool'    // Q1
  if (month <= 6) return 'Green'   // Q2
  if (month <= 9) return 'Warm'    // Q3
  return 'Amber'                    // Q4
}
function monthShape(month: number): 'circle' | 'square' | 'triangle' {
  // 四半期内のインデックス (0/1/2)
  const inQuarter = (month - 1) % 3
  return inQuarter === 0 ? 'circle' : inQuarter === 1 ? 'square' : 'triangle'
}
function monthColor(month: number, isLight: boolean): string {
  return catColor(monthQuarterKey(month), isLight)
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
        color: monthColor(mon, isLight),
        shape: monthShape(mon),
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
  }, [records, isLight])

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
              {t('auto.ConditionPCAScatter.variance_pc', { label: t('condition.pca.variance_explained'), ev1: (pca.ev1 * 100).toFixed(1), ev2: (pca.ev2 * 100).toFixed(1) })}
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
                  {/* color × shape combo: 季節色 (4) × 季節内 shape (3) = 12 識別。
                     shape ごとに別 Scatter を発行することで recharts に shape を
                     系列単位で渡せる (per-point shape はバージョン依存で挙動が
                     不安定なため、shape 別に group して描画する)。 */}
                  {(['circle', 'square', 'triangle'] as const).map((sh) => {
                    const pts = pca.points.filter((p) => p.shape === sh)
                    if (pts.length === 0) return null
                    return (
                      <Scatter key={sh} data={pts} shape={sh}>
                        {pts.map((p, i) => (
                          <Cell key={i} fill={p.color} />
                        ))}
                      </Scatter>
                    )
                  })}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            {/* 凡例: 色 = 月の四半期 (Q1〜Q4)、形 = 四半期内の月 (color × shape)。
               12 色ベタ並びは色弱で識別不能だったため、色を 4 グループに絞って
               月内位置を ●■▲ で示す方式へ。「春夏秋冬」表記は東南アジア / 南半球で
               誤解されるため使わない (四半期グループのみ)。 */}
            <div className={`mt-2 flex flex-wrap items-center gap-3 text-[11px] ${textMuted}`}>
              {[
                { label: t('auto.ConditionPCAScatter.k1'), months: [1, 2, 3], key: 'Cool' as const },
                { label: t('auto.ConditionPCAScatter.k2'), months: [4, 5, 6], key: 'Green' as const },
                { label: t('auto.ConditionPCAScatter.k3'), months: [7, 8, 9], key: 'Warm' as const },
                { label: t('auto.ConditionPCAScatter.k4'), months: [10, 11, 12], key: 'Amber' as const },
              ].map(({ label, months, key }) => (
                <span key={label} className="inline-flex items-center gap-1.5">
                  <span style={{ color: catColor(key, isLight), fontWeight: 600 }}>{label}</span>
                  {months.map((m) => (
                    <span key={m} className="inline-flex items-center gap-0.5">
                      <span style={{
                        width: 8, height: 8,
                        background: monthColor(m, isLight),
                        display: 'inline-block',
                        borderRadius: monthShape(m) === 'circle' ? 9999 : monthShape(m) === 'square' ? 0 : 0,
                        clipPath: monthShape(m) === 'triangle' ? 'polygon(50% 0%, 0% 100%, 100% 100%)' : undefined,
                      }} />
                      <span>{m}</span>
                    </span>
                  ))}
                </span>
              ))}
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
