import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// fix/auth-reader-youtube2: PR #258 で認証の保存先が localStorage だけになったが、
// src/components/session/YouTubeLivePanel.tsx は DRM 開始時に
// sessionStorage.getItem('shuttlescope_token') で直接読んでおり、常に空だった。
// 該当箇所は authStorage の getAuthItem(TOKEN_KEY) に置き換えた。このテストは
// localStorage にトークンを入れた状態で、DRM 開始がそのトークンを使うことを確かめる。

const apiPost = vi.fn()
const apiGet = vi.fn()

vi.mock('@/api/client', () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiGet: (...args: unknown[]) => apiGet(...args),
}))

import { YouTubeLivePanel } from '../YouTubeLivePanel'
import { TOKEN_KEY } from '@/api/authStorage'

describe('YouTubeLivePanel DRM start reads the token from localStorage via getAuthItem', () => {
  const drmStart = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiPost.mockReset()
    apiGet.mockReset()
    drmStart.mockReset()
    drmStart.mockResolvedValue(undefined)
    // DRM 経路に入るため start は drm_required を返す。
    apiPost.mockResolvedValue({
      job_id: 'job-1',
      status: 'probing',
      method: 'drm_required',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
    // startPoll が走るので status を 1 回返しておく。
    apiGet.mockResolvedValue({
      job_id: 'job-1',
      status: 'stopped',
      method: 'drm',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
    // isElectron 判定と DRM メソッド存在チェックを満たす。test-setup が
    // window.shuttlescope を defineProperty(writable:true) で定義済みなので、
    // その上に youtubeLiveDrmStart を生やす。
    const w = window as unknown as { shuttlescope?: Record<string, unknown> }
    w.shuttlescope = {
      ...(w.shuttlescope ?? {}),
      youtubeLiveDrmStart: drmStart,
    }
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('passes the localStorage token to youtubeLiveDrmStart', async () => {
    // 旧ビルドが残した sessionStorage の値は拾わず、localStorage を読むこと。
    sessionStorage.setItem(TOKEN_KEY, 'stale-session-token')
    localStorage.setItem(TOKEN_KEY, 'token-from-local')

    const { container } = render(<YouTubeLivePanel />)

    const input = container.querySelector('input[type="url"]') as HTMLInputElement
    expect(input).toBeTruthy()
    fireEvent.change(input, { target: { value: 'https://youtube.com/watch?v=abc' } })

    // url が state に反映されて Start ボタンの disabled が解けるまで待つ。
    const startButton = screen.getByRole('button') as HTMLButtonElement
    await waitFor(() => expect(startButton).not.toBeDisabled())

    fireEvent.click(startButton)

    await waitFor(() => expect(drmStart).toHaveBeenCalledTimes(1))
    expect(drmStart).toHaveBeenCalledWith(
      'https://youtube.com/watch?v=abc',
      'job-1',
      'token-from-local',
    )
  })
})
