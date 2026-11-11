import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { computeDeviceConnected } from '../DeviceManagerPanel'

// Presence (symptoms c/d): a PC-side device row must show exactly one state.
// computeDeviceConnected is the single source of truth: connected only when
// the PC WebSocket is up AND the last heartbeat is within the TTL (30s).
// The row gates its sending/receiving indicator and heartbeat hint on this
// value, so proving this function also proves '1 state per row'.

const NOW = new Date('2026-11-10T19:47:00.000Z').getTime()

function hb(secondsAgo: number): string {
  return new Date(NOW - secondsAgo * 1000).toISOString()
}

describe('computeDeviceConnected (PC device presence)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('is disconnected whenever the PC WebSocket is down, even with a fresh heartbeat', () => {
    expect(computeDeviceConnected({ last_heartbeat: hb(1) }, false)).toBe(false)
  })

  it('is connected when WS is up and the heartbeat is fresh', () => {
    expect(computeDeviceConnected({ last_heartbeat: hb(5) }, true)).toBe(true)
  })

  it('is disconnected when the heartbeat is stale (> 30s), so sending is suppressed', () => {
    expect(computeDeviceConnected({ last_heartbeat: hb(31) }, true)).toBe(false)
  })

  it('treats exactly 30s as still connected (inclusive TTL boundary)', () => {
    expect(computeDeviceConnected({ last_heartbeat: hb(30) }, true)).toBe(true)
  })

  it('is disconnected when there is no heartbeat at all', () => {
    expect(computeDeviceConnected({ last_heartbeat: null }, true)).toBe(false)
  })
})
