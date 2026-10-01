import { describe, expect, it } from 'vitest'

import {
  chooseMobileVideoQuality,
  getMobileVideoSrc,
  type MobileQualityOption,
} from '../videoSrc'

const match = {
  id: 42,
  video_token: 'opaque-video-token',
  has_video_local: true,
}

describe('getMobileVideoSrc quality contract', () => {
  it('keeps backend auto selection only when quality is omitted', () => {
    const url = getMobileVideoSrc(match)
    expect(url).toContain('token=opaque-video-token')
    expect(url).not.toContain('quality=')
  })

  it('makes source an explicit source request', () => {
    expect(getMobileVideoSrc(match, 'source')).toContain('&quality=source')
  })

  it('can explicitly request the H.264 compatibility copy', () => {
    expect(getMobileVideoSrc(match, 'play')).toContain('&quality=play')
  })
})

describe('chooseMobileVideoQuality', () => {
  const pendingPlay: MobileQualityOption[] = [
    { quality: 'source', height: 720, ready: true },
    { quality: 'play', height: 720, ready: false },
  ]

  it('falls back to source while a required compatibility copy is preparing', () => {
    expect(chooseMobileVideoQuality(pendingPlay, 'hd')).toBe('source')
  })

  it('prefers a ready H.264 copy on a fresh resolution', () => {
    const ready = pendingPlay.map((q) =>
      q.quality === 'play' ? { ...q, ready: true } : q,
    )
    expect(chooseMobileVideoQuality(ready, 'hd')).toBe('play')
  })

  it('promotes the same pending preference to H.264 once it becomes ready', () => {
    const requested = 'hd' as const
    expect(chooseMobileVideoQuality(pendingPlay, requested)).toBe('source')

    const ready = pendingPlay.map((q) =>
      q.quality === 'play' ? { ...q, ready: true } : q,
    )
    expect(chooseMobileVideoQuality(ready, requested)).toBe('play')
  })

  it('respects an explicit source choice even when H.264 is ready', () => {
    const ready = pendingPlay.map((q) =>
      q.quality === 'play' ? { ...q, ready: true } : q,
    )
    expect(chooseMobileVideoQuality(ready, 'source')).toBe('source')
  })
})
