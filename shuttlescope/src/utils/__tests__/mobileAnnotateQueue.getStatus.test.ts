/**
 * Audit #616: getStatus() must not report an empty queue when IndexedDB is
 * unreadable. On a storage failure it returns ok:false so the UI can show an
 * explicit storage-error state instead of silently claiming "nothing unsent".
 *
 * fake-indexeddb is not a dependency, so we stub the minimal IndexedDB surface
 * that openDb()/getStatus() touch (open -> onsuccess/onerror, a readonly
 * transaction, objectStore.getAll).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getStatus } from '../mobileAnnotateQueue'

type Req = { onsuccess?: () => void; onerror?: () => void; result?: unknown; error?: unknown }

function installWorkingIndexedDb(items: unknown[]) {
  const store = {
    getAll() {
      const req: Req = {}
      req.result = items
      queueMicrotask(() => req.onsuccess?.())
      return req
    },
  }
  const db = {
    objectStoreNames: { contains: () => true },
    createObjectStore: () => store,
    transaction: () => ({ objectStore: () => store, abort: () => { throw new Error('no reuse') } }),
    close: () => undefined,
  }
  vi.stubGlobal('indexedDB', {
    open: () => {
      const req: Req = {}
      req.result = db
      queueMicrotask(() => req.onsuccess?.())
      return req
    },
  })
}

function installBrokenIndexedDb() {
  vi.stubGlobal('indexedDB', {
    open: () => {
      const req: Req = {}
      req.error = new Error('quota / storage unavailable')
      queueMicrotask(() => req.onerror?.())
      return req
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getStatus storage health (audit #616)', () => {
  it('reports ok:true with real counts when IndexedDB is readable', async () => {
    installWorkingIndexedDb([])
    const s = await getStatus()
    expect(s.ok).toBe(true)
    expect(s.pending).toBe(0)
  })

  it('reports ok:false (not an empty-but-ok queue) when IndexedDB cannot be opened', async () => {
    installBrokenIndexedDb()
    const s = await getStatus()
    expect(s.ok).toBe(false)
    // counts are zeroed but must never be read as "nothing unsent" while ok is false
    expect(s.pending).toBe(0)
    expect(s.manualRetry).toBe(0)
    expect(s.unknownOwner).toBe(0)
  })
})
