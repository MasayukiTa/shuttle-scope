import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiGetReportBlob = vi.fn()
vi.mock('@/api/client', () => ({
  apiGetReportBlob: (path: string) => apiGetReportBlob(path),
}))

import { downloadReport, isExpectedReportType, ReportContentTypeError } from '../downloadReport'

describe('isExpectedReportType', () => {
  it('accepts pdf and json for matching extensions', () => {
    expect(isExpectedReportType('a.pdf', 'application/pdf')).toBe(true)
    expect(isExpectedReportType('a.json', 'application/json; charset=utf-8')).toBe(true)
  })

  it('rejects error bodies saved under a report file name', () => {
    expect(isExpectedReportType('a.pdf', 'application/json')).toBe(false)
    expect(isExpectedReportType('a.pdf', 'text/html')).toBe(false)
    expect(isExpectedReportType('a.json', 'text/html')).toBe(false)
    expect(isExpectedReportType('a.json', '')).toBe(false)
  })
})

describe('downloadReport', () => {
  const createObjectURL = vi.fn(() => 'blob:test')
  const revokeObjectURL = vi.fn()
  let clicked = 0

  beforeEach(() => {
    apiGetReportBlob.mockReset()
    createObjectURL.mockClear()
    revokeObjectURL.mockClear()
    clicked = 0
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }))
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
      clicked += 1
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('strips the /api prefix and saves a valid report', async () => {
    apiGetReportBlob.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    await downloadReport('/api/reports/condition_pdf?player_id=1', 'condition_1.pdf')
    expect(apiGetReportBlob).toHaveBeenCalledWith('/reports/condition_pdf?player_id=1')
    expect(clicked).toBe(1)
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
  })

  it('does not save anything when the request fails (401 / 500)', async () => {
    apiGetReportBlob.mockRejectedValue(Object.assign(new Error('unauthorized'), { status: 401 }))
    await expect(downloadReport('/api/reports/x', 'report.pdf')).rejects.toThrow('unauthorized')
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(clicked).toBe(0)
  })

  it('does not save a 200 response whose content type is not the expected file type', async () => {
    apiGetReportBlob.mockResolvedValue(new Blob(['{"detail":"x"}'], { type: 'application/json' }))
    await expect(downloadReport('/api/reports/x', 'report.pdf')).rejects.toBeInstanceOf(ReportContentTypeError)
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(clicked).toBe(0)
  })
})
