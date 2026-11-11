/**
 * SimpleHeightDiffCard — 簡易分析「打球の高さ差」の最小表示（要望8 / SD-08）
 *
 * 顧客要望として出た «簡単な分析»。打った側と受けた側の打球の高さ
 * （0〜3）の差を集計した結果を、対象試合ごとに小さなカードで見せる。計算は
 * バックエンドの /analysis/simple/height_diff が行い、ここは取得して並べるだけ。
 *
 * «細かい分析» のカード群とは別の、依存の少ない独立コンポーネント。
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchSimpleHeightDiff, type SimpleHeightDiffData } from '@/api/simpleHeightDiff'

interface SimpleHeightDiffCardProps {
  /** 対象試合 ID */
  matchId: number
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: SimpleHeightDiffData }

export function SimpleHeightDiffCard({ matchId }: SimpleHeightDiffCardProps) {
  const { t } = useTranslation()
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
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

      {state.status === 'loading' && (
        <p className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.loading')}</p>
      )}

      {state.status === 'error' && (
        <p className="text-xs text-[var(--ss-danger)]">{t('simple_analysis.error')}</p>
      )}

      {state.status === 'ready' && state.data.pairs === 0 && (
        <p className="text-xs text-[var(--ss-t3)]">{t('simple_analysis.no_data')}</p>
      )}

      {state.status === 'ready' && state.data.pairs > 0 && (
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
                    {t('simple_analysis.bucket_unit', { n: state.data.distribution[level] ?? 0 })}
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
