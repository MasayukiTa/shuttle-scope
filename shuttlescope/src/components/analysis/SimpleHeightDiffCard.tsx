/**
 * SimpleHeightDiffCard — 簡易分析「打球の高さ差」の表示（要望8 / SD-08）
 *
 * ダブルスの試合での打点の高さの差を、ペアごとの平均と内訳（差 0～3）
 * として小さなカードで見せる。pairs データを props で直接渡せるほか、
 * matchId を渡すとバックエンドの /analysis/simple/height_diff から取得する。
 *
 * props が無い・空のときでも落ちないよう、全ての配列に既定値を入れる。
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchSimpleHeightDiff, type SimpleHeightDiffData } from '@/api/simpleHeightDiff'

/** 1 ペア分の高さ差集計 */
export interface PairHeightDiff {
  /** ペア名（無ければ pair_label で補う） */
  name?: string
  /** 高さ差（0～3）の平均。組が無ければ null */
  meanDiff: number | null
  /** 差の値ごとの件数 {"0":.., "1":.., "2":.., "3":..} */
  distribution?: Record<string, number>
}

interface SimpleHeightDiffCardProps {
  /** 対象試合 ID（渡すと API から取得する） */
  matchId?: number
  /** ペアごとの内訳を props で直接渡すとき */
  pairsDetail?: PairHeightDiff[]
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: SimpleHeightDiffData }

/** distribution を安全に読む */
function bucketCount(dist: Record<string, number> | undefined, level: string): number {
  return (dist ?? {})[level] ?? 0
}

export function SimpleHeightDiffCard({ matchId, pairsDetail = [] }: SimpleHeightDiffCardProps) {
  const { t } = useTranslation()
  const [state, setState] = useState<LoadState>({ status: matchId == null ? 'idle' : 'loading' })

  useEffect(() => {
    if (matchId == null) {
      setState({ status: 'idle' })
      return
    }
    let alive = true
    setState({ status: 'loading' })
    fetchSimpleHeightDiff(matchId)
      .then((res) => {
        if (!alive) return
        if (res.success && res.data) {
          setState({ status: 'ready', data: res.data })
        } else {
          setState({ status: 'error' })
        }
      })
      .catch(() => {
        if (alive) setState({ status: 'error' })
      })
    return () => {
      alive = false
    }
  }, [matchId])

  // props で pairsDetail が渡されたときはそれを優先する。
  // 無い・空でも ?? [] で .length が安全。
  const pairs = pairsDetail ?? []
  const hasDirect = pairs.length > 0

  const meanOfDirect =
    pairs.length === 0
      ? null
      : (() => {
          const vals = pairs.map((p) => p.meanDiff).filter((v): v is number => v != null)
          if (vals.length === 0) return null
          return vals.reduce((a, b) => a + b, 0) / vals.length
        })()

  return (
    <section
      className="rounded-ss-md border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-3 flex flex-col gap-2"
      aria-label={t('simple_analysis.height_diff_title')}
    >
      <header className="flex flex-col gap-0.5">
        <h3 className="text-sm font-semibold text-[var(--ss-t1)]">
          {t('simple_analysis.height_diff_title')}
        </h3>
        <p className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.height_diff_desc')}</p>
      </header>

      {/* 直接 props モード：ペアごとの平均と内訳 */}
      {hasDirect && (
        <div className="flex flex-col gap-2">
          <div className="flex gap-4">
            <div className="flex flex-col">
              <span className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.pairs')}</span>
              <span className="ss-num text-base font-bold text-[var(--ss-t1)]">
                {t('simple_analysis.pairs_unit', { n: pairs.length })}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.mean_diff')}</span>
              <span className="ss-num text-base font-bold text-[var(--ss-t1)]">
                {meanOfDirect == null ? '—' : meanOfDirect.toFixed(2)}
              </span>
            </div>
          </div>

          <ul className="flex flex-col gap-1">
            {pairs.map((pair, i) => (
              <li
                key={pair.name ?? i}
                className="flex flex-col gap-1 rounded-ss-sm border border-[var(--ss-border)] bg-[var(--ss-surface-2)] p-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--ss-t1)]">
                    {pair.name ?? t('simple_analysis.pair_label', { n: i + 1 })}
                  </span>
                  <span className="ss-num text-sm font-bold text-[var(--ss-t1)]">
                    {pair.meanDiff == null ? '—' : pair.meanDiff.toFixed(2)}
                  </span>
                </div>
                <ul className="grid grid-cols-4 gap-1">
                  {['0', '1', '2', '3'].map((level) => (
                    <li
                      key={level}
                      className="flex flex-col items-center rounded-ss-sm bg-[var(--ss-surface-1)] py-1"
                    >
                      <span className="text-[10px] text-[var(--ss-t3)]">
                        {t('simple_analysis.diff_bucket', { level })}
                      </span>
                      <span className="ss-num text-sm font-bold text-[var(--ss-t1)]">
                        {t('simple_analysis.bucket_unit', { n: bucketCount(pair.distribution, level) })}
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* API モード（matchId 指定、かつ pairsDetail が空） */}
      {!hasDirect && state.status === 'loading' && (
        <p className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.loading')}</p>
      )}

      {!hasDirect && state.status === 'error' && (
        <p className="text-xs text-[var(--ss-danger)]">{t('simple_analysis.error')}</p>
      )}

      {!hasDirect && state.status === 'ready' && state.data.pairs === 0 && (
        <p className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.no_data')}</p>
      )}

      {!hasDirect && state.status === 'idle' && (
        <p className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.no_data')}</p>
      )}

      {!hasDirect && state.status === 'ready' && state.data.pairs > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex gap-4">
            <div className="flex flex-col">
              <span className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.pairs')}</span>
              <span className="ss-num text-base font-bold text-[var(--ss-t1)]">
                {t('simple_analysis.pairs_unit', { n: state.data.pairs })}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.mean_diff')}</span>
              <span className="ss-num text-base font-bold text-[var(--ss-t1)]">
                {state.data.mean_diff == null ? '—' : state.data.mean_diff.toFixed(2)}
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.distribution')}</span>
            <ul className="grid grid-cols-4 gap-1">
              {['0', '1', '2', '3'].map((level) => (
                <li
                  key={level}
                  className="flex flex-col items-center rounded-ss-sm border border-[var(--ss-border)] bg-[var(--ss-surface-2)] py-1"
                >
                  <span className="text-[10px] text-[var(--ss-t3)]">
                    {t('simple_analysis.diff_bucket', { level })}
                  </span>
                  <span className="ss-num text-sm font-bold text-[var(--ss-t1)]">
                    {t('simple_analysis.bucket_unit', { n: bucketCount(state.data.distribution, level) })}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  )
}
