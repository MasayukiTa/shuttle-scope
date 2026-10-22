import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiGetBlob = vi.fn()
const saveBlobAs = vi.fn()
vi.mock('@/api/client', () => ({ apiGetBlob: (...a: unknown[]) => apiGetBlob(...a) }))
vi.mock('@/utils/saveBlob', () => ({ saveBlobAs: (...a: unknown[]) => saveBlobAs(...a) }))

import { downloadExpertExport } from '@/utils/expertExport'

describe('downloadExpertExport', () => {
  beforeEach(() => {
    apiGetBlob.mockReset()
    saveBlobAs.mockReset()
  })

  it('fetches with the authenticated helper and saves under the server file name', async () => {
    const blob = new Blob(['x'])
    apiGetBlob.mockResolvedValue({ blob, filename: 'server.csv' })
    const r = await downloadExpertExport('/v1/expert/export', { match_id: 3, fmt: 'csv' }, 'fallback.csv')
    expect(r).toBe('ok')
    expect(apiGetBlob).toHaveBeenCalledWith('/v1/expert/export', { match_id: 3, fmt: 'csv' })
    expect(saveBlobAs).toHaveBeenCalledWith(blob, 'server.csv')
  })

  it('uses the fallback name when the server sends none', async () => {
    const blob = new Blob(['x'])
    apiGetBlob.mockResolvedValue({ blob, filename: null })
    await downloadExpertExport('/v1/expert/export', { match_id: 3, fmt: 'json' }, 'fallback.json')
    expect(saveBlobAs).toHaveBeenCalledWith(blob, 'fallback.json')
  })

  it('reports denied for 401/403 and failed otherwise, without saving', async () => {
    apiGetBlob.mockRejectedValueOnce({ status: 403 })
    expect(await downloadExpertExport('/p', {}, 'f')).toBe('denied')
    apiGetBlob.mockRejectedValueOnce({ status: 500 })
    expect(await downloadExpertExport('/p', {}, 'f')).toBe('failed')
    apiGetBlob.mockRejectedValueOnce(new Error('network'))
    expect(await downloadExpertExport('/p', {}, 'f')).toBe('failed')
    expect(saveBlobAs).not.toHaveBeenCalled()
  })
})
