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
