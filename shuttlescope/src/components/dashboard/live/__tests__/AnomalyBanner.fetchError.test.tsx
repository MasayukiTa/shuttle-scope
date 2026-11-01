/**
 * AnomalyBanner: fetch failure (isError) must NOT collapse into the no-anomaly
 * hidden state. It renders an explicit "could not update" message (audit #636).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

const qref = vi.hoisted(() => ({ value: { data: undefined, isError: true } as unknown }))
vi.mock('@tanstack/react-query', () => ({ useQuery: () => qref.value }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn() }))

import i18n from '@/i18n'
import { AnomalyBanner } from '../AnomalyBanner'

afterEach(() => cleanup())

describe('AnomalyBanner fetch error (#636)', () => {
  it('shows an explicit error instead of hiding on fetch failure', () => {
    qref.value = { data: undefined, isError: true }
    render(<AnomalyBanner playerId={1} matchId={2} />)
    expect(screen.getByText(i18n.t('auto.AnomalyBanner.fetch_error'))).toBeTruthy()
  })

  it('stays hidden on success with anomaly=false (true empty)', () => {
    qref.value = { data: { anomaly: false }, isError: false }
    const { container } = render(<AnomalyBanner playerId={1} matchId={2} />)
    expect(container.firstChild).toBeNull()
    expect(screen.queryByText(i18n.t('auto.AnomalyBanner.fetch_error'))).toBeNull()
  })
})
