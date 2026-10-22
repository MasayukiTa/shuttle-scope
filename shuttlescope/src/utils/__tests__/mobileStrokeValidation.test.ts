import { describe, expect, it } from 'vitest'
import { asZoneCode, strokeValidationError } from '@/utils/mobileStrokeValidation'

describe('strokeValidationError', () => {
  it('allows smash landing near the net (not physically impossible)', () => {
    for (const zone of ['NL', 'NC', 'NR'] as const) {
      expect(strokeValidationError('smash', zone, 3)).toBeNull()
    }
  })

  it('still rejects short_service and net_shot landing at the back', () => {
    expect(strokeValidationError('short_service', 'BC', 1)).toBe('invalid_land')
    expect(strokeValidationError('net_shot', 'BL', 2)).toBe('invalid_land')
  })

  it('rejects a landing zone on cant_reach', () => {
    expect(strokeValidationError('cant_reach', 'ML', 2)).toBe('cant_reach_land')
    expect(strokeValidationError('cant_reach', null, 2)).toBeNull()
  })

  it('rejects serve types after the first stroke', () => {
    expect(strokeValidationError('long_service', 'BC', 2)).toBe('service_not_first')
    expect(strokeValidationError('long_service', 'BC', 1)).toBeNull()
  })
})

describe('asZoneCode', () => {
  it('keeps 9-grid zones and drops everything else', () => {
    expect(asZoneCode('NL')).toBe('NL')
    expect(asZoneCode('OB_BC')).toBeNull()
    expect(asZoneCode(null)).toBeNull()
    expect(asZoneCode(undefined)).toBeNull()
  })
})
