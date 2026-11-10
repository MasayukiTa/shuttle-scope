import { describe, expect, it } from 'vitest'
import { isPlayerSearchBlocked } from '@/utils/playerSearchGuard'

describe('isPlayerSearchBlocked', () => {
  it('blocks when a typed, unselected field has a failed search', () => {
    expect(isPlayerSearchBlocked([{ id: '', query: '山田', failed: true }])).toBe(true)
  })

  it('does not block when the search succeeded (zero candidates is a real answer)', () => {
    expect(isPlayerSearchBlocked([{ id: '', query: '山田', failed: false }])).toBe(false)
  })

  it('does not block when a player is already selected or nothing is typed', () => {
    expect(isPlayerSearchBlocked([{ id: 12, query: '山田', failed: true }])).toBe(false)
    expect(isPlayerSearchBlocked([{ id: '', query: '   ', failed: true }])).toBe(false)
  })

  it('blocks if any one of several fields is affected', () => {
    expect(
      isPlayerSearchBlocked([
        { id: 1, query: 'a', failed: false },
        { id: '', query: 'b', failed: true },
      ]),
    ).toBe(true)
  })
})
