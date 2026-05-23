import { useEffect, useState } from 'react'
import { HashRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { List, BarChart2, Settings, Sun, Moon, TrendingUp, Heart, ClipboardCheck, Users, LogOut, Bell } from 'lucide-react'
import { clsx } from 'clsx'

import '@/i18n'
import { MatchListPage } from '@/pages/MatchListPage'
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
import { closeTutorial, useTutorialChannel } from '@/components/tutorial/useTutorial'
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
  icon: typeof List
  badge?: number | null
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
  const unreadCountQuery = useQuery({
    queryKey: ['public-inquiries-unread-count'],
    queryFn: publicInquiryUnreadCount,
    enabled: role === 'admin',
    refetchInterval: 30_000,
  })
  const unreadCount = unreadCountQuery.data?.data?.count ?? 0

  const navItems: NavItem[] = [
    { to: '/matches', label: t('nav.matches'), icon: List },
    { to: '/condition', label: t('nav.condition'), icon: Heart },
    // 解析タブ: 全ロールが /dashboard にアクセス可。player には
    // DashboardTopNav 側で overview / growth のみ表示し、review / advanced /
    // research は個別 route で /dashboard/overview に redirect する。
    // CLAUDE.md non-negotiable rule (確信が持てない解析は player に出さない)
    // は dashboard 内部で守られる。
    { to: '/dashboard', label: t('nav.dashboard'), icon: BarChart2 },
    // prediction / expert_labeler は引き続き player 非表示。
    // - prediction: 絶対勝率 = CLAUDE.md "Never show player-facing screens
    //   raw absolute win-rate style judgments" 違反。
    // - expert_labeler: 専門ラベラー、player 業務外。
    ...(role !== 'player' && hasPageAccess('prediction')
      ? [{ to: '/prediction', label: t('nav.prediction'), icon: TrendingUp }]
      : []),
    ...(role !== 'player' && hasPageAccess('expert_labeler')
      ? [{ to: '/expert-labeler', label: t('nav.expert'), icon: ClipboardCheck }]
      : []),
    ...(role === 'admin'
      ? [
          { to: '/notifications', label: t('auto.App.k2'), shortLabel: '通知', icon: Bell, badge: unreadCount > 0 ? unreadCount : null },
          { to: '/users', label: t('nav.users'), icon: Users },
        ]
      : []),
    { to: '/settings', label: t('nav.settings'), icon: Settings },
  ]

  const sidebarBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'

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
      <div className={clsx('hidden md:flex w-16 lg:w-56 flex-col border-r', sidebarBg, isFullBleedPage && 'md:hidden')}>
        {/* ロゴ帯: theme に応じて bg と text を切り替える。
           ダークモードでフレームだけ白く残るバグ修正 (2026-05-19)。
           favicon が白背景でも、コンテナ側を theme に合わせ、画像はそのまま乗せる。 */}
        <div className={clsx(
          'w-full flex items-center justify-center lg:justify-start lg:px-3 lg:gap-2 py-2 border-b',
          isLight ? 'bg-white border-gray-200' : 'bg-gray-900 border-gray-700',
        )}>
          <img src="/favicon.png" alt="ShuttleScope" className="w-10 h-10 object-contain" />
          <span className={clsx(
            'hidden lg:inline text-sm font-bold truncate',
            isLight ? 'text-gray-900' : 'text-gray-100',
          )}>{t('app.name')}</span>
        </div>
        <div className="pt-4" />
        {navItems.map(({ to, label, shortLabel, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              clsx(
                // md は icon+短縮ラベル縦積み、lg+ は icon+フルラベル横並び
                'flex items-center gap-1 p-2 rounded text-xs w-full',
                'flex-col lg:flex-row lg:gap-3 lg:px-3 lg:text-sm',
                isActive
                  ? (isLight ? 'text-blue-600 bg-blue-50' : 'text-blue-400 bg-blue-900/30')
                  : (isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700')
              )
            }
          >
            <div className="relative shrink-0">
              <Icon size={20} />
              {badge ? (
                <span className="absolute -top-2 -right-2 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] leading-4 text-center">
                  {badge > 99 ? '99+' : badge}
                </span>
              ) : null}
            </div>
            {/* md: 短縮 / lg+: フルラベル */}
            <span className="text-[9px] leading-none lg:hidden">{shortLabel ?? label.slice(0, 4)}</span>
            <span className="hidden lg:inline truncate">{label}</span>
          </NavLink>
        ))}

        <div className="mt-auto mb-2 w-full">
          <button
            onClick={handleLogout}
            title={t('auth.logout')}
            className={clsx(
              'mb-2 flex items-center gap-1 p-2 rounded text-xs w-full transition-colors',
              'flex-col lg:flex-row lg:gap-3 lg:px-3 lg:text-sm',
              isLight ? 'text-gray-500 hover:text-red-700 hover:bg-red-50' : 'text-gray-400 hover:text-red-300 hover:bg-gray-700',
            )}
          >
            <LogOut size={18} className="shrink-0" />
            <span className="text-[9px] leading-none lg:hidden">{t('auth.logout')}</span>
            <span className="hidden lg:inline">{t('auth.logout')}</span>
          </button>
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            className={clsx(
              'flex items-center gap-1 p-2 rounded text-xs w-full transition-colors',
              'flex-col lg:flex-row lg:gap-3 lg:px-3 lg:text-sm',
              isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700',
            )}
          >
            {theme === 'dark' ? <Sun size={18} className="shrink-0" /> : <Moon size={18} className="shrink-0" />}
            <span className="text-[9px] leading-none lg:hidden">{theme === 'dark' ? 'Light' : 'Dark'}</span>
            <span className="hidden lg:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
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
          {navItems.map(({ to, label, shortLabel, icon: Icon, badge }) => (
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
                <Icon size={22} />
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
 * `/annotator/:matchId` を viewport 幅で振り分けるラッパ。
 * 768px 未満 (= ほぼスマホ) なら MobileAnnotatePage を内部 redirect で開く。
 * ブラウザ width を監視するので、横向き iPad などで分岐が変わっても追従する。
 */
function AnnotatorOrMobileAnnotate() {
  const { matchId } = useParams<{ matchId: string }>()
  const [isSmall, setIsSmall] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.innerWidth < 768 : false,
  )
  useEffect(() => {
    const onResize = () => setIsSmall(window.innerWidth < 768)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  if (isSmall && matchId) {
    return <Navigate to={`/m/annotate/${matchId}`} replace />
  }
  return <AnnotatorPage />
}


function MainLayout() {

  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex-1 overflow-hidden ss-main-shell">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/matches" replace />} />
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
      .catch(() => {
        if (cancelled) return
        clearRole()
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
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
        <div className="text-center space-y-3">
          <div className="text-2xl font-bold" style={{ color: 'var(--ss-text-primary, #f9fafb)' }}>{t('app.name')}</div>
          <p className="text-sm" style={{ color: 'var(--ss-text-muted, #9ca3af)' }}>{t('auto.App.k1')}</p>
        </div>
      </div>
    )
  }

  if (!token || !role) {
    return <LoginPage onLogin={() => { window.location.hash = '/matches' }} />
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
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
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

  if (!id) return null
  const tut = TUTORIALS[id as keyof typeof TUTORIALS]
  if (!tut) return null
  return <TutorialOverlay tutorial={tut} onClose={() => closeTutorial()} />
}

export default App
