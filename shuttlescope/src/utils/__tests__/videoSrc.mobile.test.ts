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

describe('getMobileVideoSrc with availability', () => {
  it('builds no stream URL when no quality is ready (local-only video)', () => {
    const none: MobileQualityOption[] = [{ quality: 'source', height: 0, ready: false }]
    expect(getMobileVideoSrc(match, 'source', none)).toBe('')
  })

  it('still builds the stream URL when the source is ready', () => {
    const ready: MobileQualityOption[] = [{ quality: 'source', height: 720, ready: true }]
    expect(getMobileVideoSrc(match, 'source', ready)).toContain('token=opaque-video-token')
  })

  it('falls back to a playable external URL when the stored video is local-only', () => {
    const none: MobileQualityOption[] = [{ quality: 'source', height: 0, ready: false }]
    const withUrl = { ...match, video_url: 'https://example.com/v.mp4' }
    expect(getMobileVideoSrc(withUrl, 'source', none)).toBe('https://example.com/v.mp4')
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
