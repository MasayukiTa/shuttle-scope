import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { uploadVideoInChunks } from '../chunkUpload'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function testFile(): File {
  return new File([new Uint8Array([1, 2, 3, 4])], 'clip.mp4', {
    type: 'video/mp4',
    lastModified: 123456,
  })
}

describe('chunkUpload retry and resume hardening', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('does not retry a permanent 4xx chunk failure', async () => {
    let chunkAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/video/init')) {
        return jsonResponse({
          upload_id: 'upload-1',
          chunk_size: 4,
          total_chunks: 1,
          received_indices: [],
        })
      }
      if (url.includes('/video/chunk')) {
        chunkAttempts += 1
        return jsonResponse({ detail: 'forbidden' }, 403)
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(uploadVideoInChunks({
      file: testFile(),
      matchId: 7,
      chunkSize: 4,
      maxRetriesPerChunk: 5,
      throttleMbps: 1_000_000,
    })).rejects.toThrow(/403/)

    expect(chunkAttempts).toBe(1)
  })

  it('discards an inconsistent resume record and starts a fresh upload', async () => {
    const file = testFile()
    const key = `shuttlescope.chunkUpload.inflight:7|${file.name}|${file.size}|${file.lastModified}`
    localStorage.setItem(key, JSON.stringify({
      uploadId: 'stale-upload',
      matchId: 7,
      fileSize: file.size,
      fileName: file.name,
      lastModified: file.lastModified,
      chunkSize: 2,
    }))

    const urls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      urls.push(url)

      if (url.includes('/stale-upload/status')) {
        return jsonResponse({
          upload_id: 'stale-upload',
          status: 'uploading',
          received_count: 0,
          total_chunks: 99,
          received_indices: [],
        })
      }
      if (url.includes('/video/init')) {
        return jsonResponse({
          upload_id: 'fresh-upload',
          chunk_size: 4,
          total_chunks: 1,
          received_indices: [],
        })
      }
      if (url.includes('/video/chunk')) {
        return jsonResponse({ success: true, received_count: 1 })
      }
      if (url.includes('/fresh-upload/finalize')) {
        return jsonResponse({
          upload_id: 'fresh-upload',
          status: 'completed',
          filename: 'clip.mp4',
          match_id: 7,
        })
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await uploadVideoInChunks({
      file,
      matchId: 7,
      chunkSize: 4,
      throttleMbps: 1_000_000,
    })

    expect(result.uploadId).toBe('fresh-upload')
    expect(urls.some((u) => u.includes('/stale-upload/status'))).toBe(true)
    expect(urls.some((u) => u.includes('/video/init'))).toBe(true)
    expect(urls.some((u) => u.includes('/fresh-upload/finalize'))).toBe(true)
    expect(localStorage.getItem(key)).toBeNull()
  })
})
