/**
 * YouTubeLivePanel auth token source test.
 *
 * PR 258 で認証の保存先が localStorage に統一された。YouTubeLivePanel の DRM 開始
 * 経路は以前 sessionStorage.getItem('shuttlescope_token') を直接読んでいたため常に
 * 空になっていた。ここでは localStorage にトークンを入れた状態で DRM 開始を起こし、
 * パネルが getAuthItem(TOKEN_KEY) 経由で localStorage のトークンを使うことを確かめる。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TOKEN_KEY } from '../../../api/authStorage'

const apiPost = vi.fn()
const apiGet = vi.fn()

vi.mock('../../../api/client', () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiGet: (...args: unknown[]) => apiGet(...args),
}))

import { YouTubeLivePanel } from '../YouTubeLivePanel'

describe('YouTubeLivePanel auth token source', () => {
  beforeEach(() => {
    apiPost.mockReset()
    apiGet.mockReset()
    vi.useRealTimers()
  })

  it('DRM 開始時に localStorage のトークンを使う (getAuthItem 経由)', async () => {
    localStorage.setItem(TOKEN_KEY, 'LS_TOKEN_123')
    // sessionStorage には別の値を置き、万一そちらを読んでいたら区別できるようにする。
    sessionStorage.setItem(TOKEN_KEY, 'SESSION_TOKEN_SHOULD_NOT_BE_USED')

    const drmStart = vi.fn().mockResolvedValue(undefined)
    ;(window as unknown as { shuttlescope: Record<string, unknown> }).shuttlescope = {
      youtubeLiveDrmStart: drmStart,
    }

    apiPost.mockResolvedValueOnce({
      job_id: 'job-1',
      status: 'probing',
      method: 'drm_required',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })

    render(<YouTubeLivePanel />)

    const urlInput = screen.getByPlaceholderText(/youtube/i) as HTMLInputElement
    fireEvent.change(urlInput, { target: { value: 'https://youtu.be/live' } })

    const startBtn = screen.getByRole('button')
    fireEvent.click(startBtn)

    await waitFor(() => expect(drmStart).toHaveBeenCalled())

    // 3 番目の引数が token。localStorage の値が渡されていること。
    const call = drmStart.mock.calls[0]
    expect(call[1]).toBe('job-1')
    expect(call[2]).toBe('LS_TOKEN_123')
    expect(call[2]).not.toBe('SESSION_TOKEN_SHOULD_NOT_BE_USED')
  })
})
