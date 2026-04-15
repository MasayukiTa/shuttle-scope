import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useConditions, type ConditionRecord } from '@/hooks/useConditions'
import { useAuth } from '@/hooks/useAuth'
import { pearson } from '@/utils/stats'

// コンディション指標間の Pearson 相関ヒートマップ (coach/analyst 専用)
//
// ConditionRecord 型 (src/hooks/useConditions.ts) は f1〜f5 / ccs を含まない。
// これらは ConditionResult 側の派生スコアで、list API (/api/conditions) からは
// 取得できないため、本コンポーネントでは useConditions で得られる生列のみ対象にする。
// UI では「f1〜f5, ccs は対象外」の注記を表示する。

interface Props {
  playerId: number
  isLight: boolean
}

// ConditionRecord から取り得る候補列 (数値のみ)
type NumericKey = keyof ConditionRecord
const CANDIDATE_KEYS: NumericKey[] = [
  'ccs',
  'f1',
  'f2',
  'f3',
  'f4',
  'f5',
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

const MIN_N = 5

// -1=青(cool), 0=中立(白/灰), +1=赤(warm) の厳密 2色グラデーション
// オレンジ/黄緑が混じらないよう、HSL ではなく単純線形補間を使う。
// 正: 中立色 → #ef4444 (red-500)
// 負: 中立色 → #3b82f6 (blue-500)
function lerpChannel(from: number, to: number, a: number): number {
  return Math.round(from + (to - from) * a)
}
function colorFor(r: number | null, isLight: boolean): string {
  if (r == null) return isLight ? '#f3f4f6' : '#374151'
  const a = Math.min(1, Math.abs(r))
  // 中立 (r=0)
  const nR = isLight ? 255 : 55
  const nG = isLight ? 255 : 65
  const nB = isLight ? 255 : 81
  // 端
  // 色ルール: 正相関=青(良い), 負相関=赤(悪い) で統一 (プロジェクト規約)
  const endR = r >= 0 ? 59 : 239 // #3b82f6 / #ef4444
  const endG = r >= 0 ? 130 : 68
  const endB = r >= 0 ? 246 : 68
  return `rgb(${lerpChannel(nR, endR, a)}, ${lerpChannel(nG, endG, a)}, ${lerpChannel(nB, endB, a)})`
}

function textOnCell(r: number | null, isLight: boolean): string {
  if (r == null) return isLight ? '#9ca3af' : '#9ca3af'
  // 濃い色のときは白、薄い色のときは既定色
  if (Math.abs(r) > 0.55) return '#ffffff'
  return isLight ? '#111827' : '#f3f4f6'
}

export function ConditionCorrelationHeatmap({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { data: records, isLoading, error } = useConditions(playerId, { limit: 200 })
  const [selected, setSelected] = useState<{
    xi: number
    yi: number
    r: number | null
    n: number
  } | null>(null)

  // player ロールには非表示
  if (role === 'player') return null

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const labelColor = isLight ? 'text-gray-700' : 'text-gray-200'

  // 利用可能な列を動的に選別 (各列で >=5 件の有限値がある列のみ)
  const { keys, columns } = useMemo(() => {
    const list: ConditionRecord[] = records ?? []
    const cols = new Map<NumericKey, number[]>()
    for (const k of CANDIDATE_KEYS) {
      const arr: number[] = []
      for (const rec of list) {
        const v = rec[k] as unknown
        if (typeof v === 'number' && Number.isFinite(v)) arr.push(v)
      }
      if (arr.length >= MIN_N) cols.set(k, arr)
    }
    // ただし相関計算はペア単位なので、候補は「値が >=5 件ある列」に絞る
    const availableKeys = Array.from(cols.keys())
    // 各レコードの値ベクトルを列順で揃える
    const columnVectors: Array<Array<number | null>> = availableKeys.map((k) =>
      list.map((rec) => {
        const v = rec[k] as unknown
        return typeof v === 'number' && Number.isFinite(v) ? v : null
      }),
    )
    return { keys: availableKeys, columns: columnVectors }
  }, [records])

  // N×N 相関行列
  const matrix = useMemo(() => {
    const m: Array<Array<{ r: number | null; n: number }>> = []
    for (let i = 0; i < keys.length; i++) {
      const row: Array<{ r: number | null; n: number }> = []
      for (let j = 0; j < keys.length; j++) {
        if (i === j) {
          row.push({ r: 1, n: columns[i].filter((v) => v != null).length })
          continue
        }
        // ペアで両方 finite な件数
        const xs: number[] = []
        const ys: number[] = []
        for (let k = 0; k < columns[i].length; k++) {
          const xi = columns[i][k]
          const yi = columns[j][k]
          if (xi != null && yi != null) {
            xs.push(xi)
            ys.push(yi)
          }
        }
        if (xs.length < MIN_N) {
          row.push({ r: null, n: xs.length })
        } else {
          const r = pearson(xs, ys)
          row.push({ r, n: xs.length })
        }
      }
      m.push(row)
    }
    return m
  }, [keys, columns])

  const labelFor = (k: NumericKey): string => t(`condition.corr_heatmap.var.${String(k)}`)

  return (
    <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <h2 className="text-sm font-semibold">{t('condition.corr_heatmap.title')}</h2>
        <span className={`text-xs ${textMuted}`}>
          {t('condition.corr_heatmap.records', { n: records?.length ?? 0 })}
        </span>
      </div>

      {isLoading ? (
        <div className={`${textMuted} text-xs`}>{t('condition.corr_heatmap.loading')}</div>
      ) : error ? (
        <div className={`${textMuted} text-xs`}>{t('condition.corr_heatmap.no_data')}</div>
      ) : keys.length < 2 ? (
        <div className={`${textMuted} text-xs`}>{t('condition.corr_heatmap.insufficient')}</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="border-collapse text-[11px]">
              <thead>
                <tr>
                  <th className="p-1"></th>
                  {keys.map((k) => (
                    <th
                      key={`h-${String(k)}`}
                      className={`p-1 text-left font-normal ${labelColor}`}
                      style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
                    >
                      {labelFor(k)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {keys.map((rk, i) => (
                  <tr key={`r-${String(rk)}`}>
                    <th
                      className={`p-1 text-right font-normal whitespace-nowrap ${labelColor}`}
                    >
                      {labelFor(rk)}
                    </th>
                    {keys.map((_ck, j) => {
                      const cell = matrix[i][j]
                      const bg = colorFor(cell.r, isLight)
                      const fg = textOnCell(cell.r, isLight)
                      const display =
                        cell.r == null ? t('condition.corr_heatmap.na') : cell.r.toFixed(2)
                      const isSel = selected && selected.xi === i && selected.yi === j
                      return (
                        <td
                          key={`c-${i}-${j}`}
                          onClick={() =>
                            setSelected({ xi: i, yi: j, r: cell.r, n: cell.n })
                          }
                          style={{
                            backgroundColor: bg,
                            color: fg,
                            width: 44,
                            height: 32,
                            textAlign: 'center',
                            cursor: 'pointer',
                            outline: isSel
                              ? `2px solid ${isLight ? '#1d4ed8' : '#60a5fa'}`
                              : '1px solid rgba(0,0,0,0.05)',
                          }}
                          title={`${labelFor(keys[i])} × ${labelFor(keys[j])}\n${t(
                            'condition.corr_heatmap.pearson_r',
                          )}: ${cell.r == null ? '—' : cell.r.toFixed(3)}  N=${cell.n}`}
                        >
                          {display}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selected && (
            <div className={`mt-3 text-xs ${textMuted}`}>
              <span className={labelColor}>
                {labelFor(keys[selected.xi])} × {labelFor(keys[selected.yi])}
              </span>
              {'  '}
              {t('condition.corr_heatmap.pearson_r')}:{' '}
              <span className="font-mono">
                {selected.r == null ? t('condition.corr_heatmap.na') : selected.r.toFixed(3)}
              </span>
              {'  '}N: <span className="font-mono">{selected.n}</span>
              {selected.r != null && selected.n < MIN_N && (
                <span className="italic ml-2">
                  {t('condition.corr_heatmap.insufficient_pair')}
                </span>
              )}
            </div>
          )}

          <div className={`mt-3 flex items-center gap-2 text-[11px] ${textMuted}`}>
            <span>{t('condition.corr_heatmap.legend_negative')}</span>
            <div
              style={{
                width: 160,
                height: 10,
                background: isLight
                  ? 'linear-gradient(to right, #ef4444, #ffffff, #3b82f6)'
                  : 'linear-gradient(to right, #ef4444, #374151, #3b82f6)',
                border: `1px solid ${isLight ? '#e5e7eb' : '#4b5563'}`,
              }}
            />
            <span>{t('condition.corr_heatmap.legend_positive')}</span>
          </div>
        </>
      )}
    </section>
  )
}

export default ConditionCorrelationHeatmap
