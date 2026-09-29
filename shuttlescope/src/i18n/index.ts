import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import ja from './ja.json'
import en from './en.json'

export const SUPPORTED_LANGS = ['ja', 'en'] as const
export type SupportedLang = (typeof SUPPORTED_LANGS)[number]

const LS_KEY = 'shuttlescope.lang'
const COOKIE_KEY = 'ss_lang'

// 親ドメイン Cookie を使って shuttle-scope.com と app.shuttle-scope.com の間で言語設定を共有する。
// URL が `*.shuttle-scope.com` の場合のみ `Domain=.shuttle-scope.com` を付与する。
// それ以外（localhost / Electron file:// / 他ドメイン）では Domain 属性なしで通常の Cookie として機能する。
function isShuttleScopeDomain(): boolean {
  try {
    const h = typeof window !== 'undefined' ? window.location.hostname : ''
    return h === 'shuttle-scope.com' || h.endsWith('.shuttle-scope.com')
  } catch { return false }
}

function readCookie(name: string): string | null {
  try {
    if (typeof document === 'undefined') return null
    const m = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'))
    return m ? decodeURIComponent(m[1]) : null
  } catch { return null }
}

function writeCookie(name: string, value: string) {
  try {
    if (typeof document === 'undefined') return
    const maxAge = 60 * 60 * 24 * 365  // 1年
    const domain = isShuttleScopeDomain() ? '; Domain=.shuttle-scope.com' : ''
    const secure = window.location.protocol === 'https:' ? '; Secure' : ''
    document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; SameSite=Lax${domain}${secure}`
  } catch { /* ignore */ }
}

function detectInitialLang(): SupportedLang {
  // 優先順位: URL ?lang=xx（ランディング→アプリ遷移時の明示指定）
  //        → Cookie (.shuttle-scope.com で共有)
  //        → localStorage（同一オリジン永続化）
  //        → ブラウザ言語（en なら en、それ以外は ja）
  try {
    if (typeof window !== 'undefined') {
      const q = new URLSearchParams(window.location.search).get('lang')
      if (q === 'ja' || q === 'en') return q
    }
  } catch { /* ignore */ }
  const c = readCookie(COOKIE_KEY)
  if (c === 'ja' || c === 'en') return c
  try {
    const saved = localStorage.getItem(LS_KEY)
    if (saved === 'ja' || saved === 'en') return saved
  } catch { /* ignore */ }
  try {
    if (typeof navigator !== 'undefined') {
      const nav = (navigator.language || '').toLowerCase()
      if (nav.startsWith('en')) return 'en'
    }
  } catch { /* ignore */ }
  return 'ja'
}

i18n.use(initReactI18next).init({
  resources: {
    ja: { translation: ja },
    en: { translation: en },
  },
  lng: detectInitialLang(),
  fallbackLng: 'ja',
  interpolation: { escapeValue: false },
})

export function setLanguage(lang: SupportedLang) {
  try { localStorage.setItem(LS_KEY, lang) } catch { /* ignore */ }
  writeCookie(COOKIE_KEY, lang)
  i18n.changeLanguage(lang)
}

export default i18n
