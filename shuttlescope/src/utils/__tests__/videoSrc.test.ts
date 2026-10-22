import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from '@/api/client'
import { getRecordingVideoSrc, getVideoLabel, isInternalVideoFilename } from '../videoSrc'

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
