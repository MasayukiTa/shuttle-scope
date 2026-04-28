import { useEffect, useRef } from 'react'

/**
 * Cloudflare Turnstile ウィジェット。
 *
 * 設定:
 *   - import.meta.env.VITE_SS_TURNSTILE_SITE_KEY が設定されていればウィジェット表示
 *   - 未設定 (dev) 時は何も表示せず、onToken に空文字を即座に渡す (skip)
 *
 * 使い方:
 * ```tsx
 * const [tsToken, setTsToken] = useState('')
 * <TurnstileWidget onToken={setTsToken} />
 * <button onClick={() => apiPost('/auth/register', { ..., turnstile_token: tsToken })}>
 * ```
 */
declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, opts: any) => string
      remove: (id: string) => void
      reset: (id?: string) => void
    }
  }
}

const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'

interface Props {
  onToken: (token: string) => void
  onExpired?: () => void
  theme?: 'light' | 'dark' | 'auto'
}

export function TurnstileWidget({ onToken, onExpired, theme = 'auto' }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const widgetIdRef = useRef<string | null>(null)
  const siteKey = (import.meta.env.VITE_SS_TURNSTILE_SITE_KEY as string | undefined) ?? ''

  useEffect(() => {
    if (!siteKey) {
      // dev / 未設定時: トークン要求なしで進める
      onToken('')
      return
    }

    let cancelled = false
    const ensureScript = () => new Promise<void>((resolve, reject) => {
      if (window.turnstile) return resolve()
      const existing = document.querySelector(`script[src^="${SCRIPT_SRC.split('?')[0]}"]`)
      if (existing) {
        existing.addEventListener('load', () => resolve())
        existing.addEventListener('error', () => reject(new Error('turnstile script load failed')))
        return
      }
      const s = document.createElement('script')
      s.src = SCRIPT_SRC
      s.async = true
      s.defer = true
      s.onload = () => resolve()
      s.onerror = () => reject(new Error('turnstile script load failed'))
      document.head.appendChild(s)
    })

    ensureScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.turnstile) return
        widgetIdRef.current = window.turnstile.render(containerRef.current, {
          sitekey: siteKey,
          theme,
          callback: (token: string) => onToken(token),
          'expired-callback': () => {
            onToken('')
            onExpired?.()
          },
          'error-callback': () => onToken(''),
        })
      })
      .catch((err) => {
        console.warn('[turnstile] failed to load:', err)
        onToken('')
      })

    return () => {
      cancelled = true
      if (widgetIdRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetIdRef.current)
        } catch {
          // noop
        }
      }
    }
  }, [siteKey, theme])

  if (!siteKey) return null
  return <div ref={containerRef} className="cf-turnstile" />
}
