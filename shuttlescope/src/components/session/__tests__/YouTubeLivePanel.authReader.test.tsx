/**
 * fix/auth-reader-youtube2: 認証の保存先が localStorage だけになったが、
 * YouTubeLivePanel の DRM 録画開始経路が sessionStorage.getItem('shuttlescope_token')
 * で直接読んでおり、ログイン済みでも常に空トークンになっていた。
 * 該当箸所を authStorage の getAuthItem(TOKEN_KEY) に置き換えた。
 *
 * このテストは localStorage にトークンを入れた状態で DRM 録画を始めたとき、
 * window.shuttlescope.youtubeLiveDrmStart にその localStorage のトークンが
 * 渡る（= 該当箸所が getAuthItem 経由で localStorage を読む）ことを確かめる。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// apiPost は DRM が必要な job を返し、DRM 分岐を走らせる。apiGet
// (status ポーリング) は本テストでは使わないので無害にする。
// vi.mock はファイル先頭へ巻き上げられるため、モックが参照する関数は
// vi.hoisted で作る (そうしないとファクトリ評価時に未初期化で落ちる)。
const { apiPost, apiGet } = vi.hoisted(() => ({
  apiPost: vi.fn(),
  apiGet: vi.fn(),
}))
vi.mock('../../../api/client', () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiGet: (...args: unknown[]) => apiGet(...args),
}))

import { YouTubeLivePanel } from '../YouTubeLivePanel'
import { TOKEN_KEY } from '../../../api/authStorage'

describe('YouTubeLivePanel DRM start reads the token from localStorage', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    apiPost.mockReset()
    apiGet.mockReset()
    apiGet.mockResolvedValue({
      job_id: 'job-1',
      status: 'recording',
      method: 'drm',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
    apiPost.mockResolvedValue({
      job_id: 'job-1',
      status: 'probing',
      method: 'drm_required',
      file_size: 0,
      elapsed: 0,
      error: null,
      out_path: '',
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    localStorage.clear()
    sessionStorage.clear()
    // テストで差し込んだ DRM モックを片付ける。
    if (window.shuttlescope) delete window.shuttlescope.youtubeLiveDrmStart
  })

  it('passes the localStorage token to youtubeLiveDrmStart', async () => {
    const drmStart = vi
      .fn()
      .mockResolvedValue({ sourceId: 's-1', sourceName: 'DRM' })
    // test-setup が window.shuttlescope を定義済み (isElectron=true)。
    window.shuttlescope!.youtubeLiveDrmStart = drmStart

    // 該当箸所が読むべき値を localStorage に入れる (sessionStorage には入れない)。
    localStorage.setItem(TOKEN_KEY, 'token-from-local')

    render(<YouTubeLivePanel matchId={7} />)

    const input = screen.getByPlaceholderText(/./) as HTMLInputElement
    fireEvent.change(input, {
      target: { value: 'https://www.youtube.com/watch?v=abc' },
    })

    const startBtn = screen.getByRole('button')
    fireEvent.click(startBtn)

    await waitFor(() => expect(drmStart).toHaveBeenCalledTimes(1))
    // (url, jobId, token) の 3 引数目が localStorage のトークン。
    expect(drmStart).toHaveBeenCalledWith(
      'https://www.youtube.com/watch?v=abc',
      'job-1',
      'token-from-local',
    )
  })

  it('does not read a stale sessionStorage token', async () => {
    const drmStart = vi
      .fn()
      .mockResolvedValue({ sourceId: 's-1', sourceName: 'DRM' })
    window.shuttlescope!.youtubeLiveDrmStart = drmStart

    // 旧ビルドが残した sessionStorage の値は拾わず、localStorage を読む。
    sessionStorage.setItem(TOKEN_KEY, 'stale-session')
    localStorage.setItem(TOKEN_KEY, 'token-from-local')

    render(<YouTubeLivePanel />)

    const input = screen.getByPlaceholderText(/./) as HTMLInputElement
    fireEvent.change(input, {
      target: { value: 'https://www.youtube.com/watch?v=xyz' },
    })
    fireEvent.click(screen.getByRole('button'))

    await waitFor(() => expect(drmStart).toHaveBeenCalledTimes(1))
    expect(drmStart.mock.calls[0][2]).toBe('token-from-local')
  })
})
