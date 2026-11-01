import { describe, it, expect } from 'vitest'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

// Audit item 26: the video source selector must present usage scenarios,
// not transport/technology labels. The mode values (local/webview/none)
// are unchanged; only the user-facing labels are scenario-oriented.
describe('video_source mode labels (audit 26)', () => {
  const keys = ['mode_local', 'mode_webview', 'mode_none'] as const

  it('exist in both ja and en', () => {
    for (const k of keys) {
      expect(typeof (ja as any).video_source?.[k]).toBe('string')
      expect(typeof (en as any).video_source?.[k]).toBe('string')
      expect((ja as any).video_source[k].length).toBeGreaterThan(0)
      expect((en as any).video_source[k].length).toBeGreaterThan(0)
    }
  })

  it('ja labels are scenario based, not transport jargon', () => {
    const vs = (ja as any).video_source
    // no bare transport/technology wording
    expect(vs.mode_webview).not.toContain('中継') // "中継"
    expect(vs.mode_webview).not.toContain('（ブラウザ）') // "（ブラウザ）"
    expect(vs.mode_none).not.toContain('（現地）') // "（現地）"
    // scenario verbs present
    expect(vs.mode_local).toContain('使う') // "使う"
    expect(vs.mode_webview).toContain('カメラ') // "カメラ"
    expect(vs.mode_none).toContain('記録') // "記録"
  })

  it('en labels are scenario based, not transport jargon', () => {
    const vs = (en as any).video_source
    expect(vs.mode_webview.toLowerCase()).not.toContain('live stream (browser)')
    expect(vs.mode_none.toLowerCase()).not.toContain('on-site')
    expect(vs.mode_local.toLowerCase()).toContain('use')
    expect(vs.mode_webview.toLowerCase()).toContain('camera')
    expect(vs.mode_none.toLowerCase()).toContain('record')
  })
})
