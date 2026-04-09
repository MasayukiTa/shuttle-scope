import { useEffect, useState } from 'react'
import { HashRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { List, BarChart2, Settings, Sun, Moon, TrendingUp } from 'lucide-react'
import { clsx } from 'clsx'

import '@/i18n'
import { MatchListPage } from '@/pages/MatchListPage'
import { AnnotatorPage } from '@/pages/AnnotatorPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { SettingsPage } from '@/pages/SettingsPage'
import { VideoOnlyPage } from '@/pages/VideoOnlyPage'
import { CameraSenderPage } from '@/pages/CameraSenderPage'
import { PredictionPage } from '@/pages/PredictionPage'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { checkHealth } from '@/api/client'
import { UserRole } from '@/types'

// バックエンド起動を待機するフック
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

// ロール選択画面（POCフェーズ）
function RoleSelector({ onSelect }: { onSelect: (role: UserRole) => void }) {
  const { t } = useTranslation()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  return (
    <div className={`min-h-screen flex items-center justify-center ${isLight ? 'bg-gray-50' : 'bg-gray-900'}`}>
      <div className={`rounded-lg p-8 w-80 ${isLight ? 'bg-white shadow-lg border border-gray-200' : 'bg-gray-800'}`}>
        <div className="text-center mb-6">
          <div className={`text-3xl font-bold mb-1 ${isLight ? 'text-gray-900' : 'text-white'}`}>ShuttleScope</div>
          <div className={`text-sm ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>ロールを選択してください</div>
        </div>
        <div className="flex flex-col gap-3">
          {(['analyst', 'coach', 'player'] as UserRole[]).map((role) => (
            <button
              key={role}
              onClick={() => onSelect(role)}
              className={`py-3 px-4 rounded text-sm font-medium transition-colors ${
                isLight
                  ? 'bg-gray-100 hover:bg-blue-600 text-gray-800 hover:text-white'
                  : 'bg-gray-700 hover:bg-blue-700 text-white'
              }`}
            >
              {t(`roles.${role}`)}
            </button>
          ))}
        </div>
        <p className={`text-xs mt-4 text-center ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
          POCフェーズ: ロールはブラウザに保存されます
        </p>
      </div>
    </div>
  )
}

// サイドバー（デスクトップ: 左縦、モバイル: ボトムバー）
function Sidebar() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const location = useLocation()
  const isLight = theme === 'light'
  // アノテーションページではモバイルボトムバーを非表示（AnnotatorPage が独自ヘッダーを持つ）
  const isAnnotatorPage = location.pathname.startsWith('/annotator')

  const navItems = [
    { to: '/matches', label: t('nav.matches'), icon: List },
    { to: '/dashboard', label: t('nav.dashboard'), icon: BarChart2 },
    { to: '/prediction', label: t('nav.prediction'), icon: TrendingUp },
    { to: '/settings', label: t('nav.settings'), icon: Settings },
  ]

  const sidebarBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'

  return (
    <>
      {/* デスクトップ: 左サイドバー */}
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

        {/* テーマ切替ボタン */}
        <div className="mt-auto mb-2">
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

      {/* モバイル: ボトムナビ（アノテーションページでは非表示） */}
      {!isAnnotatorPage && <div className={`md:hidden fixed bottom-0 left-0 right-0 z-40 flex items-center justify-around border-t safe-area-bottom ${sidebarBg}`}
           style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}>
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                'flex flex-col items-center gap-0.5 py-2 px-3 text-[10px] min-w-0',
                isActive
                  ? (isLight ? 'text-blue-600' : 'text-blue-400')
                  : (isLight ? 'text-gray-500' : 'text-gray-400')
              )
            }
          >
            <Icon size={20} />
            <span className="truncate">{label.slice(0, 4)}</span>
          </NavLink>
        ))}
        <button
          onClick={toggleTheme}
          className={`flex flex-col items-center gap-0.5 py-2 px-3 text-[10px] ${
            isLight ? 'text-gray-500' : 'text-gray-400'
          }`}
        >
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          <span className="truncate">{theme === 'dark' ? 'Light' : 'Dark'}</span>
        </button>
      </div>}
    </>
  )
}

// メインレイアウト（サイドバー + コンテンツ）
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
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/prediction" element={<PredictionPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </ErrorBoundary>
      </div>
    </div>
  )
}

// テーマを html 要素に適用するためのラッパー
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

function App() {
  const { role, setRole } = useAuth()
  const { ready, elapsed } = useBackendReady()

  // バックエンド接続中はローディング画面を表示
  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--ss-bg-app, #111827)' }}>
        <div className="text-center space-y-4">
          <div className="text-3xl font-bold" style={{ color: 'var(--ss-text-primary, #f9fafb)' }}>ShuttleScope</div>
          <div className="flex items-center justify-center gap-2">
            <div className="w-4 h-4 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-4 h-4 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-4 h-4 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
          <p className="text-sm" style={{ color: 'var(--ss-text-muted, #9ca3af)' }}>バックエンド起動中...</p>
          {elapsed >= 10 && (
            <p className="text-yellow-500 text-xs">
              起動に時間がかかっています ({elapsed}秒)
              <br />Python と requirements.txt のインストールを確認してください
            </p>
          )}
        </div>
      </div>
    )
  }

  if (!role) {
    return (
      <QueryClientProvider client={queryClient}>
        <ThemeApplier>
          <RoleSelector onSelect={setRole} />
        </ThemeApplier>
      </QueryClientProvider>
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeApplier>
        <HashRouter>
          <Routes>
            {/* 別モニタ動画専用（サイドバーなし） */}
            <Route path="/video-only" element={<VideoOnlyPage />} />
            {/* LAN カメラ送信ページ（iOS/タブレット向け、サイドバーなし） */}
            <Route path="/camera/:sessionCode" element={<CameraSenderPage />} />
            <Route path="/camera" element={<CameraSenderPage />} />
            {/* 通常レイアウト */}
            <Route path="/*" element={<MainLayout />} />
          </Routes>
        </HashRouter>
      </ThemeApplier>
    </QueryClientProvider>
  )
}

export default App
