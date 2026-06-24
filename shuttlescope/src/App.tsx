import { useEffect, useState } from 'react'
import { HashRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'

import '@/i18n'
import { MatchListPage } from '@/pages/MatchListPage'
import { GettingStartedPage } from '@/pages/GettingStartedPage'
import { AnnotatorPage } from '@/pages/AnnotatorPage'
import { LiveInputPage } from '@/pages/LiveInputPage'
import { DashboardShell } from '@/pages/dashboard/DashboardShell'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { SettingsPage } from '@/pages/SettingsPage'
import { ConditionPage } from '@/pages/ConditionPage'
import { VideoOnlyPage } from '@/pages/VideoOnlyPage'
import { CameraSenderPage } from '@/pages/CameraSenderPage'
import { ViewerPage } from '@/pages/ViewerPage'
import { PredictionPage } from '@/pages/PredictionPage'
import { ExpertLabelerPage } from '@/pages/ExpertLabelerPage'
import { ExpertLabelerAnnotatePage } from '@/pages/ExpertLabelerAnnotatePage'
import LlmChatPage from '@/pages/LlmChatPage'
import { useAuth } from '@/hooks/useAuth'
import { useIdleLogout } from '@/hooks/useIdleLogout'
import { LoginPage } from '@/pages/LoginPage'
import { MobileAnnotatePage } from '@/pages/MobileAnnotatePage'
// M-A6: Self-service auth pages (register / verify / password reset / invitation)
import RegisterPage from '@/pages/RegisterPage'
import EmailVerifyPage from '@/pages/EmailVerifyPage'
import PasswordResetRequestPage from '@/pages/PasswordResetRequestPage'
import PasswordResetConfirmPage from '@/pages/PasswordResetConfirmPage'
import InvitationAcceptPage from '@/pages/InvitationAcceptPage'
import OnboardingConsentPage from '@/pages/OnboardingConsentPage'
import { NotificationInboxPage } from '@/pages/NotificationInboxPage'
import { UserManagementPage } from '@/pages/UserManagementPage'
import PendingUsersPage from '@/pages/PendingUsersPage'
// Phase Pay-1: 課金 UI (VITE_SS_BILLING_UI_ENABLED=false の間は各ページが <Navigate to="/"> で空遷移)
import AccountOrdersPage from '@/pages/AccountOrdersPage'
import AdminBillingPage from '@/pages/AdminBillingPage'
import AdminAnalyticsPage from '@/pages/AdminAnalyticsPage'
import { TutorialOverlay } from '@/components/tutorial/TutorialOverlay'
import { TUTORIALS } from '@/components/tutorial/tutorials'
import { closeTutorial, useTutorialChannel, useTutorialState } from '@/components/tutorial/useTutorial'
import { DemoModeBanner } from '@/components/tutorial/DemoModeBanner'
import { useDemoModeStore } from '@/store/demoModeStore'
import { getTutorialDemoTarget } from '@/api/client'
import CommerceLawPage from '@/pages/CommerceLawPage'
import { AuditLogPage } from '@/pages/AuditLogPage'
import { SecurityLogPage } from '@/pages/SecurityLogPage'
import { TeamManagementPage } from '@/pages/TeamManagementPage'
import { useTheme } from '@/hooks/useTheme'
import { authLogout, authMe, checkHealth, publicInquiryUnreadCount } from '@/api/client'

function useBackendReady() {
  const [ready, setReady] = useState(false)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    let cancelled = false
    const start = Date.now()

    const poll = async () => {
      while (!cancelled) {
        if (await checkHealth()) {
          if (!cancelled) setReady(true)
          return
        }
        setElapsed(Math.floor((Date.now() - start) / 1000))
        await new Promise<void>((r) => setTimeout(r, 500))
      }
    }

    poll()
    return () => {
      cancelled = true
    }
  }, [])

  return { ready, elapsed }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

type NavItem = {
  to: string
  label: string
  shortLabel?: string
  icon: string  // Material Symbols icon name (MIcon)
  badge?: number | null
}

// サイドバー折りたたみ状態の localStorage キー。
// 値は 'true' / 'false' の文字列。未保存 (=null) のときは未設定扱いとし、
// 「/llm 初回はデフォルト折りたたみ」のヒューリスティックを適用する。
const SIDEBAR_COLLAPSED_KEY = 'ss.sidebar.collapsed'

function readStoredSidebarCollapsed(): boolean | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)
    if (raw === 'true') return true
    if (raw === 'false') return false
    return null
  } catch {
    // localStorage が使えない (プライベートモード等) 場合は未設定扱い。
    return null
  }
}

function Sidebar() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { role, clearRole, hasPageAccess } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const location = useLocation()
  const isLight = theme === 'light'
  const isAnnotatorPage = location.pathname.startsWith('/annotator')
  // Phase C LiveInputPage もフルブリード扱い (サイドバー/ボトムナビ非表示)
  const isFullBleedPage = isAnnotatorPage || location.pathname.startsWith('/live')
  const isLlmPage = location.pathname === '/llm' || location.pathname.startsWith('/llm/')

  // ユーザが明示的にトグルしたか (= localStorage に保存値があるか)。
  // 明示選択があるとそれが最優先で、ルート依存の自動デフォルトは適用しない。
  const [hasExplicitChoice, setHasExplicitChoice] = useState<boolean>(
    () => readStoredSidebarCollapsed() !== null,
  )

  // 折りたたみ状態。デスクトップ (md+) でのみ意味を持つ。
  // 初期値: 保存値があればそれを優先。未保存なら /llm のときだけデフォルト折りたたみ
  // (チャットに全幅を割り当てるため)。それ以外のルートは従来通り展開。
  // 一度ユーザがトグルすると localStorage に永続化され、以後は保存値が優先される。
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    const stored = readStoredSidebarCollapsed()
    if (stored !== null) return stored
    return isLlmPage
  })

  // 明示選択がまだ無い間は、ルートに応じてデフォルトを追従させる:
  // /llm に入ったら自動で折りたたみ、出たら展開に戻す。
  // ユーザが一度でもトグルしたら (hasExplicitChoice=true) この自動制御は止まる。
  useEffect(() => {
    if (hasExplicitChoice) return
    setCollapsed(isLlmPage)
  }, [isLlmPage, hasExplicitChoice])

  const toggleCollapsed = () => {
    setHasExplicitChoice(true)
    setCollapsed((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next))
      } catch {
        // 永続化に失敗してもセッション内の動作は維持する。
      }
      return next
    })
  }
  const unreadCountQuery = useQuery({
    queryKey: ['public-inquiries-unread-count'],
    queryFn: publicInquiryUnreadCount,
    enabled: role === 'admin',
    refetchInterval: 30_000,
  })
  const unreadCount = unreadCountQuery.data?.data?.count ?? 0

  // LLM 専用ユーザ (バドミントン role を持たない = 'llm' 等) はバドミントン系ナビを出さない。
  const llmOnly = !!role && !['admin', 'analyst', 'coach', 'player', 'demo'].includes(role)
  const navItems: NavItem[] = [
    ...(!llmOnly
      ? [
          { to: '/getting-started', label: t('nav.getting_started'), icon: 'menu_book' },
          { to: '/matches', label: t('nav.matches'), icon: 'list' },
          { to: '/condition', label: t('nav.condition'), icon: 'favorite' },
          // 解析タブ: 全ロールが /dashboard にアクセス可。player には
          // DashboardTopNav 側で overview / growth のみ表示し、review / advanced /
          // research は個別 route で /dashboard/overview に redirect する。
          { to: '/dashboard', label: t('nav.dashboard'), icon: 'bar_chart' },
        ]
      : []),
    // prediction / expert_labeler は引き続き player / LLM 専用 非表示。
    ...(!llmOnly && role !== 'player' && hasPageAccess('prediction')
      ? [{ to: '/prediction', label: t('nav.prediction'), icon: 'trending_up' }]
      : []),
    ...(!llmOnly && role !== 'player' && hasPageAccess('expert_labeler')
      ? [{ to: '/expert-labeler', label: t('nav.expert'), icon: 'assignment_turned_in' }]
      : []),
    // 汎用 LLM チャット: llm grant を持つユーザ (admin/analyst/coach 自動 or LLM 専用)。
    ...(hasPageAccess('llm')
      ? [{ to: '/llm', label: t('nav.llm'), icon: 'forum' }]
      : []),
    ...(role === 'admin'
      ? [
          { to: '/notifications', label: t('auto.App.k2'), shortLabel: '通知', icon: 'notifications', badge: unreadCount > 0 ? unreadCount : null },
          { to: '/users', label: t('nav.users'), icon: 'group' },
        ]
      : []),
    { to: '/settings', label: t('nav.settings'), icon: 'settings' },
  ]

  const sidebarBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'

  // 折りたたみ時はあらゆるブレークポイントでアイコンのみのスリムレール (w-16) に固定し、
  // lg+ のラベル展開 (w-56) を抑止する。展開時は従来のレスポンシブ挙動を完全維持する。
  //   - railWidthCls : コンテナ幅
  //   - rowLayoutCls : nav/ボタン 1 行のレイアウト (アイコン中央 or アイコン+ラベル横並び)
  //   - logoBarCls   : ロゴ帯の整列
  //   - showFullLabel: lg+ フルラベル span を出すか
  //   - showShortLabel: md 短縮ラベル span を出すか
  const railWidthCls = collapsed ? 'w-16' : 'w-16 lg:w-56'
  const rowLayoutCls = collapsed
    ? 'flex-col justify-center'
    : 'flex-col lg:flex-row lg:gap-3 lg:px-3 lg:text-sm'
  const logoBarCls = collapsed
    ? 'justify-center'
    : 'justify-center lg:justify-start lg:px-3 lg:gap-2'
  const showFullLabel = !collapsed
  const showShortLabel = !collapsed

  const handleLogout = async () => {
    try {
      await authLogout()
    } catch {
      // ignore and still clear the local session
    } finally {
      clearRole()
      navigate('/', { replace: true })
    }
  }

  return (
    <>
      {/*
       * サイドバー: md (768-1023) はアイコン縦並び w-16、lg+ (1024px〜=iPad横/PC) は
       * w-56 でラベル付きの縦ナビ。AnnotatorPage では非表示維持。
       *
       * 全幅 56 (~224px) は SPEC が想定していた iPad 横持ち向け labeled sidebar の幅。
       */}
      <div className={clsx('hidden md:flex flex-col border-r transition-[width] duration-150', railWidthCls, sidebarBg, isFullBleedPage && 'md:hidden')}>
        {/* ロゴ帯: theme に応じて bg と text を切り替える。
           ダークモードでフレームだけ白く残るバグ修正 (2026-05-19)。
           favicon が白背景でも、コンテナ側を theme に合わせ、画像はそのまま乗せる。
           折りたたみ時 (collapsed) はロゴ中央寄せ・アプリ名非表示。 */}
        <div className={clsx(
          'w-full flex items-center py-2 border-b',
          logoBarCls,
          isLight ? 'bg-white border-gray-200' : 'bg-gray-900 border-gray-700',
        )}>
          <img src="/favicon.png" alt="ShuttleScope" className="w-10 h-10 object-contain" />
          {showFullLabel && (
            <span className={clsx(
              'hidden lg:inline text-sm font-bold truncate',
              isLight ? 'text-gray-900' : 'text-gray-100',
            )}>{t('app.name')}</span>
          )}
        </div>

        {/* 折りたたみ/展開トグル。Claude/ChatGPT 風。MIcon のみ (emoji/SVG 不使用)。
           collapsed: menu (≡) を出して「開く」を示す / expanded: menu_open を出して「閉じる」。
           aria-label は i18n キー未整備のため当面は素の文字列 (英語固定) を使用。 */}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={clsx(
            'mx-2 mt-2 flex items-center gap-1 p-2 rounded text-xs transition-colors',
            collapsed ? 'justify-center' : 'justify-center lg:justify-start lg:gap-3 lg:px-3',
            isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700',
          )}
        >
          <MIcon name={collapsed ? 'menu' : 'menu_open'} size={20} className="shrink-0" />
        </button>

        <div className="pt-2" />
        {navItems.map(({ to, label, shortLabel, icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              clsx(
                // 展開時: md は icon+短縮ラベル縦積み、lg+ は icon+フルラベル横並び。
                // 折りたたみ時: 全幅でアイコン中央のみ。
                'flex items-center gap-1 p-2 rounded text-xs w-full',
                rowLayoutCls,
                isActive
                  ? (isLight ? 'text-blue-600 bg-blue-50' : 'text-blue-400 bg-blue-900/30')
                  : (isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700')
              )
            }
          >
            <div className="relative shrink-0">
              <MIcon name={icon} size={20} />
              {badge ? (
                <span className="absolute -top-2 -right-2 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] leading-4 text-center">
                  {badge > 99 ? '99+' : badge}
                </span>
              ) : null}
            </div>
            {/* md: 短縮 / lg+: フルラベル (折りたたみ時はどちらも非表示) */}
            {showShortLabel && (
              <span className="text-[9px] leading-none lg:hidden">{shortLabel ?? label.slice(0, 4)}</span>
            )}
            {showFullLabel && (
              <span className="hidden lg:inline truncate">{label}</span>
            )}
          </NavLink>
        ))}

        <div className="mt-auto mb-2 w-full">
          <button
            onClick={handleLogout}
            title={t('auth.logout')}
            className={clsx(
              'mb-2 flex items-center gap-1 p-2 rounded text-xs w-full transition-colors',
              rowLayoutCls,
              isLight ? 'text-gray-500 hover:text-red-700 hover:bg-red-50' : 'text-gray-400 hover:text-red-300 hover:bg-gray-700',
            )}
          >
            <MIcon name="logout" size={18} className="shrink-0" />
            {showShortLabel && (
              <span className="text-[9px] leading-none lg:hidden">{t('auth.logout')}</span>
            )}
            {showFullLabel && (
              <span className="hidden lg:inline">{t('auth.logout')}</span>
            )}
          </button>
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            className={clsx(
              'flex items-center gap-1 p-2 rounded text-xs w-full transition-colors',
              rowLayoutCls,
              isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700',
            )}
          >
            {theme === 'dark' ? <MIcon name="light_mode" size={18} className="shrink-0" /> : <MIcon name="dark_mode" size={18} className="shrink-0" />}
            {showShortLabel && (
              <span className="text-[9px] leading-none lg:hidden">{theme === 'dark' ? 'Light' : 'Dark'}</span>
            )}
            {showFullLabel && (
              <span className="hidden lg:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
            )}
          </button>
        </div>

        {/* サイドバー下端のロール表示は廃止 (2 文字略は「広告」と誤読される。
            フル表記する必要性も低いため UI には出さない方針)。 */}
      </div>

      {!isFullBleedPage && (
        <div
          className={`md:hidden fixed bottom-0 left-0 right-0 z-40 flex items-center justify-around border-t ${sidebarBg}`}
          style={{
            // PWA standalone モード (iPhone home-indicator) では env(safe-area-inset-bottom)
            // が ~34px になり、固定高さ 56px だと nav 中身が 22px に圧縮されて欠ける。
            // height ではなく min-height + 内部 56px 確保で対応。
            paddingBottom: 'env(safe-area-inset-bottom, 8px)',
            minHeight: 'calc(56px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          {navItems.map(({ to, label, shortLabel, icon, badge }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'flex flex-col items-center gap-0.5 py-2 px-4 text-[10px] min-w-0',
                  isActive
                    ? (isLight ? 'text-blue-600' : 'text-blue-400')
                    : (isLight ? 'text-gray-500' : 'text-gray-400')
                )
              }
            >
              <div className="relative">
                <MIcon name={icon} size={22} />
                {badge ? (
                  <span className="absolute -top-2 -right-2 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] leading-4 text-center">
                    {badge > 99 ? '99+' : badge}
                  </span>
                ) : null}
              </div>
              <span className="truncate font-medium">{shortLabel ?? label.slice(0, 4)}</span>
            </NavLink>
          ))}
        </div>
      )}
    </>
  )
}

function AdminRoute({ children }: { children: React.ReactNode }) {

  const { role } = useAuth()
  if (role !== 'admin') return <Navigate to="/matches" replace />
  return <>{children}</>
}

function PageAccessRoute({ pageKey, children }: { pageKey: string; children: React.ReactNode }) {

  const { hasPageAccess } = useAuth()
  if (!hasPageAccess(pageKey)) return <Navigate to="/matches" replace />
  return <>{children}</>
}

/**
 * `/annotator/:matchId` を端末種別で振り分けるラッパ。
 * スマホなら MobileAnnotatePage へ内部 redirect。
 *
 * 旧実装は `window.innerWidth < 768` で判定していたが、MobileAnnotatePage は
 * 横向き必須 (LandscapeGuard) なのに対し、最近のスマホは横向きにすると
 * innerWidth が長辺 (iPhone14=844, Pixel=915 …) となり 768 を超えるため、
 * 「縦→モバイル誘導→横にする→768超で AnnotatorPage に戻される」という
 * ループでほとんどのスマホが専用ページに到達できなかった。
 * → 向きに依存しない「画面の物理短辺 < 768」かつ「タッチ端末 (pointer:coarse)」
 *   で判定し、横向きでもスマホは MobileAnnotatePage に留まるようにする。
 */
function detectPhone(): boolean {
  if (typeof window === 'undefined') return false
  const sw = window.screen?.width ?? window.innerWidth
  const sh = window.screen?.height ?? window.innerHeight
  const shortEdge = Math.min(sw, sh)            // 向きに依存しない短辺
  const coarse = window.matchMedia?.('(pointer: coarse)')?.matches ?? false
  return shortEdge < 768 && coarse
}

function AnnotatorOrMobileAnnotate() {
  const { matchId } = useParams<{ matchId: string }>()
  const [isPhone, setIsPhone] = useState<boolean>(() => detectPhone())
  useEffect(() => {
    const onChange = () => setIsPhone(detectPhone())
    window.addEventListener('resize', onChange)
    window.addEventListener('orientationchange', onChange)
    return () => {
      window.removeEventListener('resize', onChange)
      window.removeEventListener('orientationchange', onChange)
    }
  }, [])
  if (isPhone && matchId) {
    return <Navigate to={`/m/annotate/${matchId}`} replace />
  }
  return <AnnotatorPage />
}


function MainLayout() {
  const { role } = useAuth()
  const location = useLocation()
  // LLM 専用ロール (バドミントン権限を持たない = 'llm' 等) を badminton 系ページに
  // 入らせない。nav では既に隠しているが、初期ルート '/' (→ /matches へ redirect) や
  // 直接 URL / bookmark 経由で到達し得るため、許可パス以外は /llm へ送る。
  // 2026-06-05: LLM 専用ユーザがログイン後 /#/matches に着地する不具合の対策。
  const llmOnly = !!role && !['admin', 'analyst', 'coach', 'player', 'demo'].includes(role)
  if (llmOnly) {
    const p = location.pathname
    const allowed =
      p === '/llm' || p.startsWith('/llm/') ||
      p === '/settings' || p.startsWith('/settings/') ||
      p.startsWith('/legal') || p.startsWith('/account')
    if (!allowed) return <Navigate to="/llm" replace />
  }

  return (
    <div className="flex ss-app-shell">
      <Sidebar />
      <div className="flex-1 overflow-hidden ss-main-shell">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/matches" replace />} />
            <Route path="/getting-started" element={<GettingStartedPage />} />
            <Route path="/matches" element={<MatchListPage />} />
            {/* R48: スマホからのアクセス時は MobileAnnotatePage に redirect。
                 既存の `navigate('/annotator/N')` 呼び出しを直接書き換えずに切替。
                 判定は viewport 幅 (< 768px) のみで、ロールは見ない (analyst/coach
                 が誤ってスマホで開いた場合も mobile UI が出る方が UX 良い)。 */}
            <Route path="/annotator/:matchId" element={<AnnotatorOrMobileAnnotate />} />
            {/* /m/annotate/:matchId は ProtectedMainRoute レベルで full-bleed
                 描画される (この Routes は MainLayout 内なので到達しない)。 */}
            {/* Phase C: 試合中専用フルブリード入力 (mobile-first MVP) */}
            <Route path="/live/:matchId" element={<LiveInputPage />} />
            <Route path="/condition" element={<ConditionPage />} />
            {/* /analysis は使用しない (dashboard に統一)。古い bookmark から
               飛んできた人を考慮して dashboard へ redirect。 */}
            <Route path="/analysis" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard/*" element={<DashboardShell />} />
            <Route path="/prediction" element={<PageAccessRoute pageKey="prediction"><PredictionPage /></PageAccessRoute>} />
            <Route path="/expert-labeler" element={<PageAccessRoute pageKey="expert_labeler"><ExpertLabelerPage /></PageAccessRoute>} />
            <Route path="/expert-labeler/:matchId" element={<PageAccessRoute pageKey="expert_labeler"><ExpertLabelerAnnotatePage /></PageAccessRoute>} />
            <Route path="/llm" element={<PageAccessRoute pageKey="llm"><LlmChatPage /></PageAccessRoute>} />
<Route path="/notifications" element={<AdminRoute><NotificationInboxPage /></AdminRoute>} />
            <Route path="/users" element={<AdminRoute><UserManagementPage /></AdminRoute>} />
            <Route path="/users/pending" element={<AdminRoute><PendingUsersPage /></AdminRoute>} />
            {/* Phase Pay-1: 課金 UI ルート。各ページは内部で BILLING_UI_ENABLED チェック */}
            <Route path="/account/orders" element={<AccountOrdersPage />} />
            <Route path="/admin/billing" element={<AdminRoute><AdminBillingPage /></AdminRoute>} />
            <Route path="/admin/analytics" element={<AdminRoute><AdminAnalyticsPage /></AdminRoute>} />
            <Route path="/legal/commerce" element={<CommerceLawPage />} />
            <Route path="/audit-logs" element={<AdminRoute><AuditLogPage /></AdminRoute>} />
            <Route path="/admin/security" element={<AdminRoute><SecurityLogPage /></AdminRoute>} />
            <Route path="/teams" element={<TeamManagementPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </ErrorBoundary>
      </div>
    </div>
  )
}

function ThemeApplier({ children }: { children: React.ReactNode }) {

  const { theme } = useTheme()
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])
  return <>{children}</>
}

const IDLE_LOGOUT_MS = 15 * 60 * 1000

function ProtectedMainRoute() {
  const { t } = useTranslation()

  const { token, role, setSession, clearRole } = useAuth()
  const [checkingAuth, setCheckingAuth] = useState(true)
  // GDPR Article 7 / APPI 第18条: 同意未取得なら OnboardingConsentPage に誘導
  const [consentRequired, setConsentRequired] = useState<boolean>(false)
  // 任意同意 (体組成開示 / AI 学習 等) の "未回答" 状態。consent_required と
  // 違ってこちらは "あとで" を選んで先送りできる。
  const [optionalConsentPending, setOptionalConsentPending] = useState<boolean>(false)

  useIdleLogout({
    enabled: !!token,
    timeoutMs: IDLE_LOGOUT_MS,
    onIdle: () => {
      authLogout().catch(() => { /* ignore */ })
      clearRole()
    },
  })

  useEffect(() => {
    let cancelled = false

    if (!token) {
      setCheckingAuth(false)
      return
    }

    setCheckingAuth(true)
    authMe()
      .then((me) => {
        if (cancelled) return
        setSession({
          token,
          role: me.role,
          userId: me.user_id ?? 0,
          playerId: me.player_id ?? null,
          teamName: me.team_name ?? null,
          displayName: me.display_name ?? null,
          pageAccess: me.page_access ?? [],
        })
        setConsentRequired(!!me.consent_required)
        setOptionalConsentPending(!!me.optional_consent_pending)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        // 401/403 (= トークン無効 / 失効 / 権限剥奪) のみ「認証無効」とみなして
        // セッションを破棄する。429 (レート制限) / 503 / timeout / ネットワーク断
        // などの一過性エラーで clearRole すると、ログイン直後にログイン画面へ
        // 弾き返される (login→login bounce) 不具合になる。
        // 再現経路: 試合一覧が match ごとに pipeline/jobs を多数並列発火して
        // rate-limit を使い切ると、同時に走る /auth/me が 429 を返し、ここで
        // 無条件 clearRole していた。一過性エラー時は login 時に保存済みの
        // token/role をそのまま維持する (authMe は再検証にすぎない)。
        const status = (err as { status?: number } | null)?.status
        if (status === 401 || status === 403) {
          clearRole()
        }
      })
      .finally(() => {
        if (!cancelled) setCheckingAuth(false)
      })

    return () => {
      cancelled = true
    }
  }, [token, setSession, clearRole])

  // R47: タイムアウトや 401 で未認証状態に落ちたとき、URL が
  // `#/dashboard/research` 等の保護パスのまま残ると第三者に「このパスが存在する」
  // ことが漏れる。LoginPage に切り替わるタイミングで hash を `#/login` に
  // replaceState してアドレスバーから保護パス情報を消す。
  // 履歴は replace で上書きするので、戻る ボタンで元の保護 URL に飛ぶこともない。
  useEffect(() => {
    if (checkingAuth) return
    if (token && role) return
    const currentHash = window.location.hash || ''
    if (currentHash === '#/login' || currentHash === '#/' || currentHash === '') return
    try {
      const cleaned = window.location.pathname + window.location.search + '#/login'
      window.history.replaceState(null, '', cleaned)
    } catch {
      // history.replaceState 失敗時は黙って fallback (LoginPage は描画されるので機能は維持)
    }
  }, [checkingAuth, token, role])

  if (checkingAuth) {
    return (
      <div className="min-h-[100svh] flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
        <div className="text-center space-y-3">
          <div className="text-2xl font-bold" style={{ color: 'var(--ss-text-primary, #f9fafb)' }}>{t('app.name')}</div>
          <p className="text-sm" style={{ color: 'var(--ss-text-muted, #9ca3af)' }}>{t('auto.App.k1')}</p>
        </div>
      </div>
    )
  }

  if (!token || !role) {
    return <LoginPage onLogin={() => {
      // LLM 専用ユーザ (バドミントン role を持たない) はログイン後 /#/llm へ直行。
      let dest = '/matches'
      try {
        const r = sessionStorage.getItem('shuttlescope_role')
        if (r && !['admin', 'analyst', 'coach', 'player', 'demo'].includes(r)) dest = '/llm'
      } catch { /* ignore */ }
      window.location.hash = dest
    }} />
  }

  // 同意未取得 → 必須同意取得画面 (フェーズ 1 / GDPR Article 7)。
  // ここで gate されている間、MainLayout 内のすべてのページにアクセス不可。
  // 任意同意のみ未回答の場合 (optionalOnly): popup は出すが「あとで」で skip 可。
  if (consentRequired || optionalConsentPending) {
    return (
      <OnboardingConsentPage
        optionalOnly={!consentRequired && optionalConsentPending}
        onCompleted={() => {
          setConsentRequired(false)
          setOptionalConsentPending(false)
        }}
        onDeferred={() => {
          // 「あとで」: optional は記録せず先送り。次回ログイン時に再 popup。
          // 必須は満たしているので consent_required は False のまま。
          setOptionalConsentPending(false)
        }}
      />
    )
  }

  // R48: /m/annotate/:matchId は MainLayout (Sidebar / bottom nav) を完全に
  // バイパスしてフルブリード描画する。スマホアノテで「下に設定タブが居る」
  // 「動画上部が URL バーに被る」問題を構造的に潰す。
  //
  // ⚠️ /m/annotate は MainLayout の ErrorBoundary をバイパスするため、
  // ここで明示的に ErrorBoundary を被せて throw を可視化する (PWA 標準モード
  // では Safari Web Inspector に繋ぐ手段が無いユーザのため、画面に出すのが
  // 唯一の診断パス)。
  return (
    <Routes>
      <Route
        path="/m/annotate/:matchId"
        element={
          <ErrorBoundary>
            <MobileAnnotatePage />
          </ErrorBoundary>
        }
      />
      <Route path="*" element={<MainLayout />} />
    </Routes>
  )
}

function App() {
  const { t } = useTranslation()
  const { ready } = useBackendReady()

  if (!ready) {
    return (
      <div className="min-h-[100svh] flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
        <div className="text-center">
          <div className="text-3xl font-bold" style={{ color: 'var(--ss-text-primary, #f9fafb)' }}>{t('app.name')}</div>
          <div className="mt-6 flex items-center justify-center gap-2">
            <div className="w-4 h-4 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-4 h-4 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-4 h-4 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeApplier>
        <DemoModeBanner />
        <GlobalTutorialMount />
        <HashRouter>
          <Routes>
            <Route path="/video-only" element={<VideoOnlyPage />} />
            <Route path="/camera/:sessionCode" element={<CameraSenderPage />} />
            <Route path="/camera" element={<CameraSenderPage />} />
            <Route path="/viewer/:sessionCode" element={<ViewerPage />} />
            <Route path="/viewer" element={<ViewerPage />} />
            {/* M-A6: 自己サービス認証経路 (ログイン不要) */}
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify" element={<EmailVerifyPage />} />
            <Route path="/password/reset" element={<PasswordResetRequestPage />} />
            <Route path="/password/reset-confirm" element={<PasswordResetConfirmPage />} />
            <Route path="/invite" element={<InvitationAcceptPage />} />
            <Route path="/*" element={<ProtectedMainRoute />} />
          </Routes>
        </HashRouter>
      </ThemeApplier>
    </QueryClientProvider>
  )
}

// demo データを見せるチュートリアル ID（解析画面の読み方）。
// ここに登録された tutorial が開いている間だけ demo モードを有効化する。
const DEMO_TUTORIAL_IDS = new Set<string>(['analysis_reading'])

function GlobalTutorialMount() {
  const id = useTutorialChannel()
  const enableDemo = useDemoModeStore((s) => s.enable)
  const disableDemo = useDemoModeStore((s) => s.disable)

  useEffect(() => {
    let cancelled = false
    if (id && DEMO_TUTORIAL_IDS.has(id)) {
      getTutorialDemoTarget()
        .then((r) => { if (!cancelled) enableDemo(r.data ?? null) })
        .catch(() => { if (!cancelled) enableDemo(null) })
    } else {
      disableDemo()
    }
    return () => { cancelled = true; disableDemo() }
  }, [id, enableDemo, disableDemo])

  const { state: tutState } = useTutorialState()
  if (!id) return null
  const tut = TUTORIALS[id as keyof typeof TUTORIALS]
  if (!tut) return null
  // 中断時に保存された last_step から再開する (status === 'in_progress' のみ)
  const rec = tutState.find((s) => s.tutorial_id === id)
  const startStep =
    rec && rec.status === 'in_progress' && rec.last_step > 0 && rec.last_step < tut.steps.length
      ? rec.last_step
      : 0
  return <TutorialOverlay tutorial={tut} onClose={() => closeTutorial()} startStep={startStep} />
}

export default App
