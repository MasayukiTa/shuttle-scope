import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from '@/api/client'
import {
  getMobileVideoSrc,
  getRecordingVideoSrc,
  getVideoLabel,
  getVideoSrc,
  hasVideo,
  isInternalVideoFilename,
  isPlayableVideoUrl,
} from '../videoSrc'

describe('non-http(s) video_url is not a playable video', () => {
  it('accepts only http and https', () => {
    expect(isPlayableVideoUrl('https://example.com/v.mp4')).toBe(true)
    expect(isPlayableVideoUrl('HTTP://example.com/v.mp4')).toBe(true)
    expect(isPlayableVideoUrl('mailto:someone@example.com')).toBe(false)
    expect(isPlayableVideoUrl('javascript:void(0)')).toBe(false)
    expect(isPlayableVideoUrl('')).toBe(false)
    expect(isPlayableVideoUrl(null)).toBe(false)
    expect(isPlayableVideoUrl(undefined)).toBe(false)
  })

  it('does not treat a stray scheme as a registered video or a source', () => {
    const bad = { id: 5, video_url: 'mailto:someone@example.com' }
    expect(hasVideo(bad)).toBe(false)
    expect(getVideoSrc(bad)).toBe('')
    expect(getMobileVideoSrc(bad)).toBe('')
    expect(getVideoLabel(bad)).toBe('')
  })

  it('keeps a valid external URL working', () => {
    const ok = { id: 5, video_url: 'https://example.com/v.mp4' }
    expect(hasVideo(ok)).toBe(true)
    expect(getVideoSrc(ok)).toBe('https://example.com/v.mp4')
    expect(getMobileVideoSrc(ok)).toBe('https://example.com/v.mp4')
  })
})

describe('getRecordingVideoSrc', () => {
  it('builds a branch-specific token stream URL', () => {
    expect(getRecordingVideoSrc({ id: 42, video_token: 'a/b?c=d' })).toBe(
      `${API_BASE_URL}/recordings/42/stream?token=a%2Fb%3Fc%3Dd`,
    )
  })

  it('refuses incomplete recording references', () => {
    expect(getRecordingVideoSrc(null)).toBe('')
    expect(getRecordingVideoSrc({ id: 42, video_token: null })).toBe('')
    expect(getRecordingVideoSrc({ id: undefined, video_token: 'token' })).toBe('')
  })
})

describe('getVideoLabel', () => {
  const uuidName = '85519b7d-aa92-4a25-893a-9511bfc35ede.mp4'

  it('shows a real file name', () => {
    expect(getVideoLabel({ video_filename: 'final_court1.mp4' })).toBe('📁 final_court1.mp4')
  })

  it('hides the internal UUID file name', () => {
    expect(isInternalVideoFilename(uuidName)).toBe(true)
    expect(isInternalVideoFilename('final_court1.mp4')).toBe(false)
    const label = getVideoLabel({ video_filename: uuidName, has_video_local: true })
    expect(label).not.toContain('85519b7d')
    expect(label).not.toBe('')
  })

  it('returns an empty label when no video is registered', () => {
    expect(getVideoLabel({})).toBe('')
    expect(getVideoLabel(null)).toBe('')
  })
})
