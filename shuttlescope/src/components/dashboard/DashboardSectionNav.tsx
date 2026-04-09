// Advanced ページ内セクション切替ナビ
import { clsx } from 'clsx'

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
  return (
    <div className="flex gap-1 flex-wrap">
      {SECTIONS.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={clsx(
            'px-3 py-1 rounded text-xs font-medium transition-colors',
            active === key
              ? 'bg-gray-600 text-white'
              : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
