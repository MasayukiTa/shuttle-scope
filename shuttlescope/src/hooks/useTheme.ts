import { useState, useEffect, useCallback } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'shuttlescope-theme'
const CHANGE_EVENT = 'shuttlescope-theme-change'

/**
 * テーマ管理フック。
 *
 * 2026-05-19 修正: 旧版は各 useTheme() 呼び出しが独立した useState を持っており、
 *   1 つのコンポーネントで toggle してもほかの useTheme 消費者は state が
 *   固まったままになる「フレームワーク失敗」を起こしていた
 *   (= ダークモード切替で frame が light のまま残る原因)。
 *
 * 新版: setter は CustomEvent + localStorage で全 useTheme インスタンスに
 *   broadcast し、すべての消費者を同期更新する。
 *   DOM 属性 data-theme も同時に書き込むため、useIsLightMode の MutationObserver
 *   経路とも一貫する。
 */
function readStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* ignore */
  }
  return 'light'
}

function applyThemeToDocument(theme: Theme): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  if (theme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

function persistTheme(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    /* ignore */
  }
}

function broadcastTheme(theme: Theme): void {
  try {
    window.dispatchEvent(new CustomEvent<Theme>(CHANGE_EVENT, { detail: theme }))
  } catch {
    /* ignore */
  }
}

export function useTheme() {
  const [theme, setLocalTheme] = useState<Theme>(readStoredTheme)

  useEffect(() => {
    // 1) 自分が初回 mount 時に DOM 属性を反映 (theme=light でも明示)
    applyThemeToDocument(theme)
    // 2) 他コンポーネントからの broadcast を購読
    const onChange = (e: Event) => {
      const next = (e as CustomEvent<Theme>).detail
      if (next === 'light' || next === 'dark') {
        setLocalTheme(next)
      }
    }
    // 3) 別タブからの localStorage 変更も拾う
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return
      const v = e.newValue
      if (v === 'light' || v === 'dark') {
        setLocalTheme(v)
      }
    }
    window.addEventListener(CHANGE_EVENT, onChange as EventListener)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange as EventListener)
      window.removeEventListener('storage', onStorage)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // theme が変わるたびに DOM 属性を更新 (CSS variables / useIsLightMode 連動)
  useEffect(() => {
    applyThemeToDocument(theme)
  }, [theme])

  const setTheme = useCallback((t: Theme) => {
    persistTheme(t)
    setLocalTheme(t)
    broadcastTheme(t)
  }, [])

  const toggleTheme = useCallback(() => {
    setLocalTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      persistTheme(next)
      broadcastTheme(next)
      return next
    })
  }, [])

  return { theme, toggleTheme, setTheme }
}
