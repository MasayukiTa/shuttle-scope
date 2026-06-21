import { useState, useEffect } from 'react'

// md ブレイクポイント（768px）未満をモバイルとみなす
const MOBILE_BREAKPOINT = 768

const MOBILE_MQ = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

export function useIsMobile(): boolean {
  // 初期値も listener と同じ matchMedia で判定する。innerWidth と matchMedia は
  // スクロールバー/ズーム時に評価軸がずれ、初回 paint と change 後で値が食い違って
  // 1フレームだけレイアウトがフリップする事故があった。単一ソースに統一する。
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_MQ).matches)

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_MQ)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    // 初期 state 算出と listener 登録の間にビューポートが変わった場合に同期する。
    setIsMobile(mql.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  return isMobile
}
