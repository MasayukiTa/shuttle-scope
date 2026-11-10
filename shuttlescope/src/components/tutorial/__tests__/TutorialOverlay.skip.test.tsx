import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'

vi.mock('@/api/client', () => ({ apiPost: vi.fn().mockResolvedValue({}), apiGet: vi.fn() }))
vi.mock('@/utils/analytics', () => ({ trackTutorialStep: vi.fn() }))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k }),
}))

import { TutorialOverlay } from '../TutorialOverlay'

const tutorial = {
  id: 't_skip',
  title: 'T',
  steps: [
    { title: 'S0', body: 'b0' },
    { title: 'S1 missing', body: 'b1', target: '[data-tutorial="nope"]' },
    { title: 'S2 present', body: 'b2', target: '[data-tutorial="here"]' },
  ],
}

describe('TutorialOverlay: 対象が無いステップの自動スキップ (A-19)', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

  it('対象要素が画面に無いステップは次へ送った先で自動的に飛ばされる', async () => {
    const el = document.createElement('div')
    el.setAttribute('data-tutorial', 'here')
    document.body.appendChild(el)
    render(<TutorialOverlay tutorial={tutorial as never} startStep={1} onClose={() => {}} />)
    expect(screen.getByText('S1 missing')).toBeTruthy()
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(screen.queryByText('S1 missing')).toBeNull()
    expect(screen.getByText('S2 present')).toBeTruthy()
  })

  it('対象がある場合は飛ばさない', async () => {
    const el = document.createElement('div')
    el.setAttribute('data-tutorial', 'nope')
    document.body.appendChild(el)
    render(<TutorialOverlay tutorial={tutorial as never} startStep={1} onClose={() => {}} />)
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(screen.getByText('S1 missing')).toBeTruthy()
  })
})
