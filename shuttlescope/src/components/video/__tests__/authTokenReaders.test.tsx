/**
 * fix/auth-readers-video: PR 258 で認証の保存先が localStorage のみになった後、
 * WebViewPlayer と YouTubeLivePanel がトークンを sessionStorage から直接読んでいて
 * 常に空になっていた。両コンポーネントを authStorage.getAuthItem(TOKEN_KEY) に
 * 置き換えたので、localStorage にトークンがある状態でそれが実際に使われることを検証する。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TOKEN_KEY } from '@/api/authStorage'

// api クライアントをモックする。drm_required の分岐を通してトークン読取まで到達させる。
const apiPost = vi.fn()
const apiGet = vi.fn()
vi.mock('@/api/client', () => ({
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiGet: (...a: unknown[]) => apiGet(...a),
}))

import { WebViewPlayer } from '../WebViewPlayer'
import { YouTubeLivePanel } from '../../session/YouTubeLivePanel'

describe('auth token readers use localStorage via getAuthItem (not sessionStorage)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiPost.mockReset()
    apiGet.mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('WebViewPlayer: screenCaptureStart receives the token stored in localStorage', async () => {
    // PR 258 後の本番状態: トークンは localStorage にだけある (sessionStorage は空)。
    localStorage.setItem(TOKEN_KEY, 'ls-webview-token')

    // backend start は drm_required を返し、Electron の screenCaptureStart へ進ませる。
    apiPost.mockResolvedValue({ job_id: 'job-1', method: 'drm_required', status: 'ok' })
    const screenCaptureStart = vi.fn().mockResolvedValue(undefined)
    const screenCaptureStop = vi.fn().mockResolvedValue(undefined)
    ;(window as unknown as { shuttlescope: Record<string, unknown> }).shuttlescope = {
      ...(window as unknown as { shuttlescope?: Record<string, unknown> }).shuttlescope,
      screenCaptureStart,
      screenCaptureStop,
    }

    render(<WebViewPlayer url="https://drm.example.com/watch/1" siteName="DRMSite" />)

    // 録画開始ボタンを押す。
    fireEvent.click(screen.getByRole('button', { name: '録画' }))

    await waitFor(() => expect(screenCaptureStart).toHaveBeenCalled())
    const arg = screenCaptureStart.mock.calls[0][0] as { token: string }
    // localStorage のトークンが使われている (sessionStorage 直読みなら空になっていた)。
    expect(arg.token).toBe('ls-webview-token')
  })

  it('YouTubeLivePanel: youtubeLiveDrmStart receives the token stored in localStorage', async () => {
    localStorage.setItem(TOKEN_KEY, 'ls-ytlive-token')

    apiPost.mockResolvedValue({
      job_id: 'job-2',
      status: 'probing',
      method: 'drm_required',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
    apiGet.mockResolvedValue({
      job_id: 'job-2',
      status: 'recording',
      method: 'drm',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
    const youtubeLiveDrmStart = vi.fn().mockResolvedValue(undefined)
    const youtubeLiveDrmStop = vi.fn().mockResolvedValue(undefined)
    ;(window as unknown as { shuttlescope: Record<string, unknown> }).shuttlescope = {
      ...(window as unknown as { shuttlescope?: Record<string, unknown> }).shuttlescope,
      youtubeLiveDrmStart,
      youtubeLiveDrmStop,
    }

    render(<YouTubeLivePanel />)

    const urlInput = screen.getByRole('textbox')
    fireEvent.change(urlInput, { target: { value: 'https://youtube.com/live/abc' } })
    fireEvent.click(screen.getByText('録画開始'))

    await waitFor(() => expect(youtubeLiveDrmStart).toHaveBeenCalled())
    const call = youtubeLiveDrmStart.mock.calls[0]
    // 第3引数が token。localStorage の値が渡っている。
    expect(call[2]).toBe('ls-ytlive-token')
  })
})
