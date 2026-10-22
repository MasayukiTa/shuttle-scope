/**
 * FilterScopeNote: 絞り込みが効くかどうかの表示は backend の応答 meta だけで決まる。
 * (filter_scope は analysis_registry の宣言。population は stamps_population が書く)
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ja from '@/i18n/ja.json'
import { FilterScopeNote } from '@/components/dashboard/ResearchNotice'
import { toFilterApiParams } from '@/utils/analysisFilterParams'
import { DEFAULT_FILTERS } from '@/types'

const RN = (ja as any).auto.ResearchNotice

describe('FilterScopeNote', () => {
  it('global_only shows the not-filtered line', () => {
    render(<FilterScopeNote meta={{ filter_scope: 'global_only' }} />)
    expect(screen.getByTestId('filter-scope-note').textContent).toBe(RN.filter_scope_global_only)
  })

  it('not_wired shows the not-filtered line', () => {
    render(<FilterScopeNote meta={{ filter_scope: 'not_wired' }} />)
    expect(screen.getByTestId('filter-scope-note').textContent).toBe(RN.filter_scope_not_wired)
  })

  it('filtered shows the population only while a filter is applied', () => {
    const { rerender } = render(
      <FilterScopeNote
        meta={{ filter_scope: 'filtered', population: { n_matches: 2, n_rallies: 30, filter_applied: false } }}
      />,
    )
    expect(screen.queryByTestId('filter-scope-note')).toBeNull()
    rerender(
      <FilterScopeNote
        meta={{ filter_scope: 'filtered', population: { n_matches: 2, n_rallies: 30, filter_applied: true } }}
      />,
    )
    expect(screen.getByTestId('filter-scope-note').textContent).toContain('2')
    expect(screen.getByTestId('filter-scope-note').textContent).toContain('30')
  })

  it('shows nothing without a declared scope', () => {
    render(<FilterScopeNote meta={{}} />)
    expect(screen.queryByTestId('filter-scope-note')).toBeNull()
  })
})

describe('toFilterApiParams', () => {
  it('sends nothing for the default filters', () => {
    expect(toFilterApiParams(DEFAULT_FILTERS)).toEqual({})
  })

  it('uses the same query names as the backend MatchFilter', () => {
    expect(
      toFilterApiParams({ result: 'win', tournamentLevel: 'IC', dateFrom: '2026-01-01', dateTo: '2026-02-01' }),
    ).toEqual({ result: 'win', tournament_level: 'IC', date_from: '2026-01-01', date_to: '2026-02-01' })
  })
})
