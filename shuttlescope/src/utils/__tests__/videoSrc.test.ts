import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from '@/api/client'
import { getRecordingVideoSrc } from '../videoSrc'

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
