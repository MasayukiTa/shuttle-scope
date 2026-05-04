// Advanced ページ内セクション切替ナビ
import { useCardTheme } from '@/hooks/useCardTheme'

export type AdvancedSection = 'shot' | 'rally' | 'transition' | 'spatial' | 'temporal' | 'opponent' | 'doubles'

const SECTIONS: { key: AdvancedSection; label: string }[] = [
  { key: 'shot',       label: 'ショット' },
  { key: 'rally',      label: 'ラリー' },
  { key: 'transition', label: '遷移' },
  { key: 'spatial',    label: '空間' },
  { key: 'temporal',   label: '時間' },
  { key: 'opponent',   label: '対戦相手' },
  { key: 'doubles',    label: 'ダブルス' },
]

interface DashboardSectionNavProps {
  active: AdvancedSection
  onChange: (section: AdvancedSection) => void
}

export function DashboardSectionNav({ active, onChange }: DashboardSectionNavProps) {
  const { isLight } = useCardTheme()
  return (
    <div className="relative">
      <div className="flex overflow-x-auto scrollbar-hide gap-1">
        {SECTIONS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={[
              'flex-shrink-0 px-3 py-1 rounded text-xs font-medium transition-colors whitespace-nowrap',
              active === key
                ? 'bg-gray-600 text-white'
                : isLight
                ? 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>
      {/* 右端フェードアウト */}
      <div className={[
        'absolute right-0 top-0 h-full w-6 pointer-events-none',
        isLight
          ? 'bg-gradient-to-l from-white to-transparent'
          : 'bg-gradient-to-l from-gray-900 to-transparent',
      ].join(' ')} />
    </div>
  )
}
