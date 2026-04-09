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
      'flex gap-1 flex-wrap px-2 py-2 border-b',
      isLight ? 'border-gray-200 bg-white' : 'border-gray-700 bg-gray-900'
    )}>
      {PAGES.map(({ path, key }) => (
        <NavLink
          key={key}
          to={path}
          className={({ isActive }) =>
            clsx(
              'px-3 py-1.5 rounded text-xs font-medium transition-colors',
              isActive
                ? (isLight ? 'bg-blue-600 text-white' : 'bg-blue-600 text-white')
                : (isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-gray-800')
            )
          }
        >
          {t(`nav.dashboard_pages.${key}`)}
        </NavLink>
      ))}
    </div>
  )
}
