import { useState, useEffect } from 'react'

/**
 * 現在のテーマがライトモードかどうかを返すフック。
 * MutationObserver で html[data-theme] の変更を監視し、
 * テーマ切り替え時にリアクティブに再レンダリングをトリガーする。
 */
export function useIsLightMode(): boolean {
  const [isLight, setIsLight] = useState<boolean>(
    () => document.documentElement.dataset.theme === 'light'
  )

  useEffect(() => {
    const obs = new MutationObserver(() => {
      setIsLight(document.documentElement.dataset.theme === 'light')
    })
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    return () => obs.disconnect()
  }, [])

  return isLight
}
