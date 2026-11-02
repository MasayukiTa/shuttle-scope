/**
 * Audit #184: the "temporal" section used the label 「時間」 but it does not use
 * real time (only rally order within a set). The label must read
 * 「スコアフェーズ」 and must not say 「時間」.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/hooks/useCardTheme', () => ({ useCardTheme: () => ({ isLight: false }) }))

import { DashboardSectionNav } from '../DashboardSectionNav'

describe('DashboardSectionNav temporal label (audit #184)', () => {
  it('labels the temporal section as スコアフェーズ and not 時間', () => {
    render(<DashboardSectionNav active="shot" onChange={() => {}} />)
    expect(screen.getByText('スコアフェーズ')).toBeTruthy()
    expect(screen.queryByText('時間')).toBeNull()
  })
})
