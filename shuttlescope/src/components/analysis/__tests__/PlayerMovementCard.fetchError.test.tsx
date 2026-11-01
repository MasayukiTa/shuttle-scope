/**
 * PlayerMovementCard: API failure (isError) must render an explicit error,
 * distinct from a successful "no tracking data" (available=false) state (audit #641).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

const qref = vi.hoisted(() => ({ value: { data: undefined, isLoading: false, isError: true } as unknown }))
vi.mock('@tanstack/react-query', () => ({ useQuery: () => qref.value }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn() }))
vi.mock('@/hooks/useCardTheme', () => ({ useCardTheme: () => ({ card: '', cardInner: '', textHeading: '', textSecondary: '', textMuted: '', textFaint: '' }) }))

import i18n from '@/i18n'
import { PlayerMovementCard } from '../PlayerMovementCard'

afterEach(() => cleanup())

const baseProps = { matchId: 1, matchFormat: 'singles', playerNames: {}, isLight: true }

describe('PlayerMovementCard fetch error (#641)', () => {
  it('shows an explicit error on API failure', () => {
    qref.value = { data: undefined, isLoading: false, isError: true }
    render(<PlayerMovementCard {...baseProps} />)
    expect(screen.getByText(i18n.t('auto.PlayerMovementCard.fetch_error'))).toBeTruthy()
  })

  it('shows no_tracks (not error) when API succeeds with available=false', () => {
    qref.value = { data: { data: { available: false } }, isLoading: false, isError: false }
    render(<PlayerMovementCard {...baseProps} />)
    expect(screen.queryByText(i18n.t('auto.PlayerMovementCard.fetch_error'))).toBeNull()
    expect(screen.getByText(i18n.t('auto.PlayerMovementCard.no_tracks'))).toBeTruthy()
  })
})
