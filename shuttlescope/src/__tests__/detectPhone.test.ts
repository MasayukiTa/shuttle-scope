/**
 * #792: /annotator/:matchId のモバイル振り分け (detectPhone) は、coarse pointer の
 * タッチ端末であれば phone だけでなく代表的な iPad viewport (短辺 768 / 810 / 820 / 834)
 * も専用モバイル Annotator (/m/annotate) 側へ送る。マウス等 fine pointer の desktop や、
 * 短辺 1024 以上の大型タブレットは従来どおり desktop AnnotatorPage とする。
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { detectPhone } from '../App'

function setEnv(opts: { w: number; h: number; coarse: boolean }) {
  vi.stubGlobal('screen', { width: opts.w, height: opts.h } as Screen)
  vi.stubGlobal(
    'matchMedia',
    ((q: string) => ({
      matches: q.includes('coarse') ? opts.coarse : false,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('detectPhone (#792 iPad 振り分け)', () => {
  it('phone (短辺 390, coarse): 専用フロー対象', () => {
    setEnv({ w: 390, h: 844, coarse: true })
    expect(detectPhone()).toBe(true)
  })

  it.each([768, 810, 820, 834])(
    'iPad 短辺 %i (coarse): 専用フロー対象になる',
    (shortEdge) => {
      setEnv({ w: shortEdge, h: 1180, coarse: true })
      expect(detectPhone()).toBe(true)
    },
  )

  it('desktop (短辺 1080, fine pointer): 専用フロー対象外', () => {
    setEnv({ w: 1920, h: 1080, coarse: false })
    expect(detectPhone()).toBe(false)
  })

  it('大型タブレット (短辺 1024, coarse): 専用フロー対象外', () => {
    setEnv({ w: 1024, h: 1366, coarse: true })
    expect(detectPhone()).toBe(false)
  })
})
