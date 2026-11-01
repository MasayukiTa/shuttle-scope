import { describe, expect, it } from 'vitest'

import { deviceNamesFromUpdate } from '../useCameraHub'

describe('deviceNamesFromUpdate (device_list_update -> display names)', () => {
  it('picks up device_name per participant from the notification', () => {
    const next = deviceNamesFromUpdate({}, [
      { participant_id: 7, stream_id: 's1', device_name: 'Court A phone' },
      { participant_id: 9, stream_id: null, device_name: 'Bench iPad' },
    ])
    expect(next).toEqual({ '7': 'Court A phone', '9': 'Bench iPad' })
  })

  it('coerces numeric participant ids to string keys', () => {
    const next = deviceNamesFromUpdate({}, [{ participant_id: 42, device_name: 'Cam' }])
    expect(next['42']).toBe('Cam')
  })

  it('trims whitespace and ignores empty or non-string names', () => {
    const next = deviceNamesFromUpdate({ '1': 'Old' }, [
      { participant_id: 1, device_name: '  Renamed  ' },
      { participant_id: 2, device_name: '   ' },
      { participant_id: 3, device_name: 123 as unknown as string },
      { participant_id: 4 },
    ])
    expect(next['1']).toBe('Renamed')
    expect(next['2']).toBeUndefined()
    expect(next['3']).toBeUndefined()
    expect(next['4']).toBeUndefined()
  })

  it('keeps a prior name when an entry has no usable device_name', () => {
    const prev = { '5': 'Keep me' }
    const next = deviceNamesFromUpdate(prev, [{ participant_id: 5, device_name: '' }])
    expect(next['5']).toBe('Keep me')
  })

  it('returns the same reference when nothing changed (stable identity)', () => {
    const prev = { '1': 'Same' }
    const next = deviceNamesFromUpdate(prev, [{ participant_id: 1, device_name: 'Same' }])
    expect(next).toBe(prev)
  })

  it('returns the previous map unchanged when devices is missing or not an array', () => {
    const prev = { '1': 'A' }
    expect(deviceNamesFromUpdate(prev, undefined)).toBe(prev)
    expect(deviceNamesFromUpdate(prev, {} as never)).toBe(prev)
  })
})
