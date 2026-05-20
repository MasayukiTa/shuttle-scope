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

// 月 (1..12) → 4 季節色 × 3 月内位置の shape で識別 (color × shape combo)。
// 12 色を並べても色弱ユーザは 4〜6 色しか識別できない (deutan で赤/橙/茶/緑/オリーブが
// 混ざる)。Design Language §6.3 ルール 4 に従い、6 を超える categorical は shape と
// 組合せる。
//   - 季節 (色):  冬 (12,1,2) = Cool 青系, 春 (3,4,5) = Green 青緑系,
//                 夏 (6,7,8) = Warm 朱系, 秋 (9,10,11) = Amber 橙系
//   - 月内位置 (shape): 季節 1 月目 = ●, 2 月目 = ■, 3 月目 = ▲
function monthSeasonKey(month: number): 'Cool' | 'Green' | 'Warm' | 'Amber' {
  if (month === 12 || month === 1 || month === 2) return 'Cool'   // 冬
  if (month >= 3 && month <= 5) return 'Green'                     // 春
  if (month >= 6 && month <= 8) return 'Warm'                      // 夏
  return 'Amber'                                                    // 秋 (9-11)
}
function monthShape(month: number): 'circle' | 'square' | 'triangle' {
  // 季節内のインデックス (0/1/2)
  const inSeason = month === 12 ? 0 : (month === 1 ? 1 : (month === 2 ? 2 : ((month - 1) % 3)))
  return inSeason === 0 ? 'circle' : inSeason === 1 ? 'square' : 'triangle'
}
function monthColor(month: number, isLight: boolean): string {
  return catColor(monthSeasonKey(month), isLight)
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
            {/* 凡例: 色 = 季節、形 = 季節内の月 (color × shape)。
               12 色ベタ並びは色弱で識別不能だったため (deutan で 8 月が同じに
               見える)、色を 4 季節に絞り、月内位置を ●■▲ で示す方式へ。 */}
            <div className={`mt-2 flex flex-wrap items-center gap-3 text-[11px] ${textMuted}`}>
              {[
                { label: '冬', months: [12, 1, 2], key: 'Cool' as const },
                { label: '春', months: [3, 4, 5], key: 'Green' as const },
                { label: '夏', months: [6, 7, 8], key: 'Warm' as const },
                { label: '秋', months: [9, 10, 11], key: 'Amber' as const },
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
