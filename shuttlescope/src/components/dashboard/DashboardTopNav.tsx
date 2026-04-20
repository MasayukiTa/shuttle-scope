import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useTheme } from '@/hooks/useTheme'

const PAGES = [
  { path: '/dashboard/overview',  key: 'overview'  },
  { path: '/dashboard/live',      key: 'live'       },
  { path: '/dashboard/review',    key: 'review'     },
  { path: '/dashboard/growth',    key: 'growth'     },
  { path: '/dashboard/advanced',  key: 'advanced'   },
  { path: '/dashboard/research',  key: 'research'   },
] as const

export function DashboardTopNav() {
  const { t } = useTranslation()
  const { theme } = useTheme()
  const isLight = theme === 'light'

  return (
    <div className={clsx(
      'border-b safe-area-top',
      isLight ? 'border-gray-200 bg-white' : 'border-gray-700 bg-gray-900'
    )}>
      <div className="relative">
        <div className="flex overflow-x-auto scrollbar-hide gap-1 px-2 py-2">
          {PAGES.map(({ path, key }) => (
            <NavLink
              key={key}
              to={path}
              className={({ isActive }) =>
                clsx(
                  'flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium transition-colors whitespace-nowrap',
                  isActive
                    ? 'bg-blue-600 text-white'
                    : (isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-gray-800')
                )
              }
            >
              {t(`nav.dashboard_pages.${key}`)}
            </NavLink>
          ))}
        </div>
        {/* 右端フェードアウト（スクロール可能を示唆） */}
        <div className={clsx(
          'absolute right-0 top-0 h-full w-8 pointer-events-none',
          isLight
            ? 'bg-gradient-to-l from-white to-transparent'
            : 'bg-gradient-to-l from-gray-900 to-transparent'
        )} />
      </div>
    </div>
  )
}
