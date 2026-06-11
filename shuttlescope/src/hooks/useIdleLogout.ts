import { useEffect, useRef } from 'react'

const IDLE_EVENTS = ['mousedown', 'keydown', 'touchstart', 'pointerdown', 'wheel', 'visibilitychange'] as const

export interface UseIdleLogoutOptions {
  enabled: boolean
  timeoutMs: number
  onIdle: () => void
}

export function useIdleLogout({ enabled, timeoutMs, onIdle }: UseIdleLogoutOptions) {
  const lastActivityRef = useRef<number>(Date.now())
  const onIdleRef = useRef(onIdle)

  useEffect(() => {
    onIdleRef.current = onIdle
  }, [onIdle])

  useEffect(() => {
    if (!enabled) return

    // 有効化された瞬間 (= ログイン直後) に活動時刻をリセットする。
    // これが無いと lastActivityRef は ProtectedMainRoute の初回マウント時刻
    // (ログイン画面表示時刻) のまま残る。ログイン画面を timeoutMs 以上
    // 開いたまま放置してからログインすると、有効化直後の最初の interval tick で
    // 「既に timeout 経過」と誤判定し、無操作でも即ログアウトされる
    // (ログイン直後にログイン画面へ戻る症状の一因)。
    lastActivityRef.current = Date.now()

    const bump = () => {
      lastActivityRef.current = Date.now()
    }

    IDLE_EVENTS.forEach(ev => window.addEventListener(ev, bump, { passive: true }))

    const interval = window.setInterval(() => {
      if (Date.now() - lastActivityRef.current >= timeoutMs) {
        onIdleRef.current()
      }
    }, 30_000)

    return () => {
      IDLE_EVENTS.forEach(ev => window.removeEventListener(ev, bump))
      window.clearInterval(interval)
    }
  }, [enabled, timeoutMs])
}
