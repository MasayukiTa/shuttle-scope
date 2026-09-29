import { beforeEach, describe, expect, it, vi } from 'vitest'

async function loadFresh() {
  vi.resetModules()
  return import('../deviceUid')
}

describe('getDeviceUid storage fallbacks', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('persists the uid in localStorage when available', async () => {
    const { getDeviceUid } = await loadFresh()
    const first = getDeviceUid()
    const second = getDeviceUid()

    expect(first).toBeTruthy()
    expect(second).toBe(first)
    expect(localStorage.getItem('ss_device_uid')).toBe(first)
  })

  it('keeps a stable fallback uid when localStorage is unavailable', async () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('local storage disabled')
    })

    const { getDeviceUid } = await loadFresh()
    const first = getDeviceUid()
    const second = getDeviceUid()

    expect(first).toBeTruthy()
    expect(second).toBe(first)
  })
})
