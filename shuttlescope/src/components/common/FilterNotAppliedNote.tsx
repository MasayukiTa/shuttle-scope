// 絞り込み条件を使わないカードに付ける注記。
// 防ぐ事象: 画面上部の絞り込み(結果・大会レベル・期間)が効いているように見えるのに、
// このカードだけ全試合で計算しており、カードごとに母集団が違うこと(監査 #153)。
import { useTranslation } from 'react-i18next'
import type { AnalysisFilters } from '@/types'

/** 結果・大会レベル・期間のどれかが既定から変わっているか。 */
export function hasActiveFilters(filters: AnalysisFilters): boolean {
  return filters.result !== 'all' || !!filters.tournamentLevel || !!filters.dateFrom || !!filters.dateTo
}

export function FilterNotAppliedNote({ filters }: { filters: AnalysisFilters }) {
  const { t } = useTranslation()
  if (!hasActiveFilters(filters)) return null
  return (
    <p className="text-[11px] text-[var(--ss-t3)]" data-testid="filter-not-applied-note">
      {t('analysis.filter_not_applied')}
    </p>
  )
}
