import { afterEach, describe, expect, it, vi } from 'vitest'
import { getParticipantIceConfig } from '@/api/client'

describe('getParticipantIceConfig', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses the session-scoped participant credential instead of an app JWT', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: { ice_servers: [{ urls: 'stun:stun.l.google.com:19302' }] },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getParticipantIceConfig('SESSION/1', 42, 'participant-secret')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/sessions/SESSION%2F1/devices/42/ice-config')
    expect(init.headers).toEqual({
      Authorization: 'Participant participant-secret',
    })
  })

  it('surfaces a participant authorization failure instead of silently returning config', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      text: async () => '{"detail":"blocked"}',
    }))

    await expect(
      getParticipantIceConfig('SESSION1', 42, 'participant-secret'),
    ).rejects.toMatchObject({ status: 403 })
  })
})
