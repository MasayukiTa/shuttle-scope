/**
 * useBreakpoint — Tailwind と整合する 5 段階レスポンシブブレークポイント。
 *
 * Tailwind 規約 (tailwind.config.js):
 *   xs:  >= 480px (custom)
 *   sm:  >= 640px
 *   md:  >= 768px
 *   lg:  >= 1024px
 *   xl:  >= 1280px
 *   2xl: >= 1536px
 *
 * 戻り値:
 *   bp: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | '2xl' (現在のサイズ階級)
 *   atLeast(name): name 以上か (例: atLeast('md') === bp が md/lg/xl/2xl)
 *   below(name):   name 未満か
 *
 * 既存 useIsMobile (md 単一しきい値) とは独立。
 * 新規実装は useBreakpoint を使い、既存箇所は段階的に移行する。
 */
import { useState, useEffect } from 'react'

// tailwind.config.js の screens と完全一致させる。
// 値が乖離するとレイアウト分岐が CSS と JS で食い違うので必ず両方を直すこと。
export const BREAKPOINTS = {
  xs: 480,
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1200,
  '2xl': 1440,
} as const

export type Breakpoint = keyof typeof BREAKPOINTS

const ORDER: Breakpoint[] = ['xs', 'sm', 'md', 'lg', 'xl', '2xl']

function classify(width: number): Breakpoint {
  // 大きい順にチェックして最初に該当したものを返す
  for (let i = ORDER.length - 1; i >= 0; i--) {
    const bp = ORDER[i]
    if (width >= BREAKPOINTS[bp]) return bp
  }
  // 480px 未満は xs として扱う (Tailwind の `<xs:` 領域)
  return 'xs'
}

export interface BreakpointInfo {
  bp: Breakpoint
  width: number
  atLeast: (name: Breakpoint) => boolean
  below: (name: Breakpoint) => boolean
}

export function useBreakpoint(): BreakpointInfo {
  const [width, setWidth] = useState(() =>
    typeof window === 'undefined' ? BREAKPOINTS.md : window.innerWidth,
  )

  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = () => setWidth(window.innerWidth)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  const bp = classify(width)
  return {
    bp,
    width,
    atLeast: (name) => ORDER.indexOf(bp) >= ORDER.indexOf(name),
    below: (name) => ORDER.indexOf(bp) < ORDER.indexOf(name),
  }
}
