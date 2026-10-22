import { describe, expect, it } from 'vitest'
import { auditEmptyReason } from '../auditLogStatus'

describe('auditEmptyReason', () => {
  it('is unknown when the status could not be loaded', () => {
    expect(auditEmptyReason(null)).toBe('unknown')
    expect(auditEmptyReason(undefined)).toBe('unknown')
  })

  it('is never_recorded when the whole table is empty', () => {
    expect(auditEmptyReason({ total: 0, latest_ts: null, oldest_ts: null })).toBe('never_recorded')
  })

  it('is filtered when the table has records the filters did not match', () => {
    expect(
      auditEmptyReason({ total: 5, latest_ts: '2026-10-21T00:00:00Z', oldest_ts: '2026-10-01T00:00:00Z' }),
    ).toBe('filtered')
  })
})
