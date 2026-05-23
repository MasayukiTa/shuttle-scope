/**
 * useTypewriter — 与えられた文字列を 1 文字ずつ徐々に表示するフック。
 *
 * - text が変わるたびに reset & restart。
 * - prefers-reduced-motion: reduce が真の環境では即時 full text を返す。
 * - enabled=false の場合も即時 full text を返す（履歴再ハイドレート用）。
 */
import { useEffect, useRef, useState } from 'react'

function prefersReducedMotion(): boolean {
  try {
    return (
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    )
  } catch {
    return false
  }
}

export function useTypewriter(
  text: string,
  speedMsPerChar: number = 25,
  enabled: boolean = true,
): { revealed: string; isTyping: boolean } {
  const [revealed, setRevealed] = useState<string>(() =>
    !enabled || prefersReducedMotion() ? text : '',
  )
  const [isTyping, setIsTyping] = useState<boolean>(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (!enabled || prefersReducedMotion() || !text) {
      setRevealed(text)
      setIsTyping(false)
      return
    }
    setRevealed('')
    setIsTyping(true)
    let i = 0
    timerRef.current = window.setInterval(() => {
      i += 1
      if (i >= text.length) {
        setRevealed(text)
        setIsTyping(false)
        if (timerRef.current != null) {
          window.clearInterval(timerRef.current)
          timerRef.current = null
        }
        return
      }
      setRevealed(text.slice(0, i))
    }, speedMsPerChar)
    return () => {
      if (timerRef.current != null) {
        window.clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [text, speedMsPerChar, enabled])

  return { revealed, isTyping }
}
