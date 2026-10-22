import { useEffect, type RefObject } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * モーダルダイアログのフォーカス管理。
 * - 開いたとき: 直前のフォーカス位置を覚え、ダイアログ内の最初の操作要素へフォーカスを移す
 *   (すでにダイアログ内にフォーカスがあれば動かさない)
 * - 開いている間: Tab / Shift+Tab をダイアログ内で循環させる
 * - 閉じたとき: 覚えておいた要素へフォーカスを戻す
 */
export function useDialogFocus(containerRef: RefObject<HTMLElement | null>, active: boolean): void {
  useEffect(() => {
    if (!active) return
    const container = containerRef.current
    if (!container) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null

    const focusables = (): HTMLElement[] =>
      Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))

    if (!container.contains(document.activeElement)) {
      const first = focusables()[0]
      if (first) first.focus()
      else {
        container.tabIndex = -1
        container.focus()
      }
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const current = document.activeElement
      if (e.shiftKey && (current === first || !container.contains(current))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (current === last || !container.contains(current))) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (previous && document.contains(previous)) previous.focus()
    }
  }, [containerRef, active])
}
