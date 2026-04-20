import { useEffect, useState } from 'react'
import { HashRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { List, BarChart2, Settings, Sun, Moon, TrendingUp, Heart, ClipboardCheck, Users, LogOut } from 'lucide-react'
import { clsx } from 'clsx'

import '@/i18n'
import { MatchListPage } from '@/pages/MatchListPage'
import { AnnotatorPage } from '@/pages/AnnotatorPage'
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
import { LoginPage } from '@/pages/LoginPage'
import { UserManagementPage } from '@/pages/UserManagementPage'
import { useTheme } from '@/hooks/useTheme'
import { authLogout, authMe, checkHealth } from '@/api/client'

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
    return () => { cancelled = true }
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

function Sidebar() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { role, clearRole } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const location = useLocation()
  const isLight = theme === 'light'
  const isAnnotatorPage = location.pathname.startsWith('/annotator')

  const navItems = [
    { to: '/matches', label: t('nav.matches'), icon: List },
    { to: '/condition', label: t('nav.condition'), icon: Heart },
    { to: '/dashboard', label: t('nav.dashboard'), icon: BarChart2 },
    { to: '/prediction', label: t('nav.prediction'), icon: TrendingUp },
    { to: '/expert-labeler', label: t('nav.expert'), icon: ClipboardCheck },
    ...(role === 'admin' ? [{ to: '/users', label: t('nav.users'), icon: Users }] : []),
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
      <div className={clsx('hidden md:flex w-16 flex-col items-center py-4 border-r', sidebarBg, isAnnotatorPage && 'md:hidden')}>
        <div className="text-blue-500 text-xs font-bold mb-4">SS</div>
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={label}
            className={({ isActive }) =>
              clsx(
                'flex flex-col items-center gap-1 p-2 rounded text-xs w-full',
                isActive
                  ? (isLight ? 'text-blue-600 bg-blue-50' : 'text-blue-400 bg-blue-900/30')
                  : (isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700')
              )
            }
          >
            <Icon size={20} />
            <span className="text-[9px] leading-none">{label.slice(0, 4)}</span>
          </NavLink>
        ))}

        <div className="mt-auto mb-2">
          <button
            onClick={handleLogout}
            title={t('auth.logout')}
            className={`mb-2 flex flex-col items-center gap-1 p-2 rounded text-xs w-full transition-colors ${
              isLight ? 'text-gray-500 hover:text-red-700 hover:bg-red-50' : 'text-gray-400 hover:text-red-300 hover:bg-gray-700'
            }`}
          >
            <LogOut size={18} />
            <span className="text-[9px] leading-none">{t('auth.logout')}</span>
          </button>
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'ライトモードに切替' : 'ダークモードに切替'}
            className={`flex flex-col items-center gap-1 p-2 rounded text-xs w-full transition-colors ${
              isLight ? 'text-gray-500 hover:text-gray-800 hover:bg-gray-100' : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            <span className="text-[9px] leading-none">{theme === 'dark' ? 'Light' : 'Dark'}</span>
          </button>
        </div>

        <div className={`text-[9px] pb-2 ${isLight ? 'text-gray-400' : 'text-gray-600'}`}>
          {role?.slice(0, 2).toUpperCase()}
        </div>
      </div>

      {!isAnnotatorPage && (
        <div
          className={`md:hidden fixed bottom-0 left-0 right-0 z-40 flex items-center justify-around border-t ${sidebarBg}`}
          style={{ paddingBottom: 'env(safe-area-inset-bottom, 8px)', height: '56px' }}
        >
          {navItems.map(({ to, label, icon: Icon }) => (
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
              <Icon size={22} />
              <span className="truncate font-medium">{label.slice(0, 4)}</span>
            </NavLink>
          ))}
        </div>
      )}
    </>
  )
}

function MainLayout() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex-1 overflow-hidden pb-14 md:pb-0">
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/matches" replace />} />
            <Route path="/matches" element={<MatchListPage />} />
            <Route path="/annotator/:matchId" element={<AnnotatorPage />} />
            <Route path="/condition" element={<ConditionPage />} />
            <Route path="/dashboard/*" element={<DashboardShell />} />
            <Route path="/prediction" element={<PredictionPage />} />
            <Route path="/expert-labeler" element={<ExpertLabelerPage />} />
            <Route path="/expert-labeler/:matchId" element={<ExpertLabelerAnnotatePage />} />
            <Route path="/users" element={<UserManagementPage />} />
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

function ProtectedMainRoute() {
  const { token, role, setSession, clearRole } = useAuth()
  const [checkingAuth, setCheckingAuth] = useState(true)

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
        })
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

  if (checkingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
        <div className="text-center space-y-3">
          <div className="text-2xl font-bold" style={{ color: 'var(--ss-text-primary, #f9fafb)' }}>ShuttleScope</div>
          <p className="text-sm" style={{ color: 'var(--ss-text-muted, #9ca3af)' }}>認証状態を確認しています...</p>
        </div>
      </div>
    )
  }

  if (!token || !role) {
    return <LoginPage onLogin={() => {}} />
  }

  return <MainLayout />
}

function App() {
  const { ready } = useBackendReady()

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
        <div className="text-center">
          <div className="text-3xl font-bold" style={{ color: 'var(--ss-text-primary, #f9fafb)' }}>ShuttleScope</div>
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
        <HashRouter>
          <Routes>
            <Route path="/video-only" element={<VideoOnlyPage />} />
            <Route path="/camera/:sessionCode" element={<CameraSenderPage />} />
            <Route path="/camera" element={<CameraSenderPage />} />
            <Route path="/viewer/:sessionCode" element={<ViewerPage />} />
            <Route path="/viewer" element={<ViewerPage />} />
            <Route path="/*" element={<ProtectedMainRoute />} />
          </Routes>
        </HashRouter>
      </ThemeApplier>
    </QueryClientProvider>
  )
}

export default App
