import { describe, expect, it, vi } from 'vitest'

import { attachRecordedVideoPath } from '../recordedVideo'

describe('S-16 録画後の動画パス登録', () => {
  it('更新が失敗したら通知され、成功扱いにはならない', async () => {
    const err = new Error('HTTP 500')
    const put = vi.fn().mockRejectedValue(err)
    const onAttached = vi.fn()
    const onError = vi.fn()

    const ok = await attachRecordedVideoPath(42, 'C:/rec/a.mp4', { put, onAttached, onError })

    expect(ok).toBe(false)
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledWith(err)
    expect(onAttached).not.toHaveBeenCalled()
  })

  it('成功したら試合を更新し、通知しない', async () => {
    const put = vi.fn().mockResolvedValue({ success: true })
    const onAttached = vi.fn()
    const onError = vi.fn()

    const ok = await attachRecordedVideoPath(42, 'C:/rec/a.mp4', { put, onAttached, onError })

    expect(ok).toBe(true)
    expect(put).toHaveBeenCalledWith('/matches/42', {
      video_local_path: 'localfile:///C:/rec/a.mp4',
      video_url: '',
    })
    expect(onAttached).toHaveBeenCalledTimes(1)
    expect(onError).not.toHaveBeenCalled()
  })
})
