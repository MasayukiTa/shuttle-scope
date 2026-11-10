import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TOKEN_KEY } from '@/api/authStorage'

// fix/auth-reader-youtube: PR #258 で認証の保存先が localStorage だけになったが、
// YouTubeLivePanel.tsx は DRM 録画開始時に sessionStorage.getItem('shuttlescope_token')
// で直接読んでいたため、ログイン後も常に空トークンを Electron の drmStart に渡していた。
// 該当箇所は authStorage の getAuthItem(TOKEN_KEY) に置き換えた。このテストは
// localStorage にトークンを入れた状態で録画を開始し、その箇所が localStorage の
// トークンを (sessionStorage の古い値ではなく) drmStart に渡すことを確かめる。

const apiPostMock = vi.fn()
const apiGetMock = vi.fn()

vi.mock('@/api/client', () => ({
  apiPost: (...args: unknown[]) => apiPostMock(...args),
  apiGet: (...args: unknown[]) => apiGetMock(...args),
}))

import { YouTubeLivePanel } from '../YouTubeLivePanel'

describe('YouTubeLivePanel reads the auth token via getAuthItem (localStorage)', () => {
  let drmStart: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiPostMock.mockReset()
    apiGetMock.mockReset()
    apiGetMock.mockResolvedValue({
      job_id: 'job-1',
      status: 'recording',
      method: 'drm',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
    drmStart = vi.fn().mockResolvedValue(undefined)
    // Electron 環境を模す。test-setup が生やした window.shuttlescope に
    // DRM メソッドを足す。
    ;(window as unknown as { shuttlescope: Record<string, unknown> }).shuttlescope = {
      version: '1.0.0',
      platform: 'test',
      youtubeLiveDrmStart: drmStart,
      youtubeLiveDrmStop: vi.fn().mockResolvedValue(undefined),
    }
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.clearAllTimers()
  })

  it('passes the localStorage token to drmStart when DRM recording starts', async () => {
    localStorage.setItem(TOKEN_KEY, 'access-from-local')
    // 旧ビルドが残した sessionStorage の値は拾わないことも併せて確認する。
    sessionStorage.setItem(TOKEN_KEY, 'stale-session')

    apiPostMock.mockResolvedValueOnce({
      job_id: 'job-1',
      status: 'probing',
      method: 'drm_required',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })

    render(<YouTubeLivePanel />)

    const input = screen.getByPlaceholderText(/.*/) as HTMLInputElement
    fireEvent.change(input, { target: { value: 'https://www.youtube.com/watch?v=abc' } })

    const startBtn = screen.getByRole('button')
    fireEvent.click(startBtn)

    await waitFor(() => expect(drmStart).toHaveBeenCalledTimes(1))

    // drmStart(url, jobId, token) の第3引数が localStorage のトークンであること。
    const tokenArg = drmStart.mock.calls[0][2]
    expect(tokenArg).toBe('access-from-local')
    expect(tokenArg).not.toBe('stale-session')
  })
})
