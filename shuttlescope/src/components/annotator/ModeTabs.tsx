/**
 * U2: AnnotatorPage 上バー左の 4 モードタブ.
 *
 * 入力 / 確認 / 解析 / 設定 を切替。
 * アイコンは Google Material Symbols (Outlined) を使用 (@/components/common/MIcon)。
 */
import { clsx } from 'clsx'

import { MIcon } from '@/components/common/MIcon'
import { AnnotatorMode, useAnnotatorModeStore } from '@/store/annotatorModeStore'

interface TabSpec {
  key: AnnotatorMode
  label: string
  shortLabel: string
  icon: string  // Material Symbols name
}

const TABS: TabSpec[] = [
  { key: 'input',    label: '入力', shortLabel: '入力', icon: 'edit_note' },
  { key: 'review',   label: '確認', shortLabel: '確認', icon: 'visibility' },
  { key: 'analysis', label: '解析', shortLabel: '解析', icon: 'analytics' },
  { key: 'settings', label: '設定', shortLabel: '設定', icon: 'settings' },
]

interface ModeTabsProps {
  isMobile?: boolean
  className?: string
}

export function ModeTabs({ isMobile, className }: ModeTabsProps) {
  const mode = useAnnotatorModeStore((s) => s.mode)
  const setMode = useAnnotatorModeStore((s) => s.setMode)
  return (
    <div
      className={clsx('flex items-center gap-0.5 shrink-0', className)}
      role="tablist"
      aria-label="モード切替"
    >
      {TABS.map(({ key, label, shortLabel, icon }) => {
        const active = mode === key
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => setMode(key)}
            className={clsx(
              'flex items-center gap-1 rounded font-medium transition-colors',
              isMobile ? 'px-1.5 py-1 text-[10px]' : 'px-2.5 py-1.5 text-xs',
              active
                ? 'bg-blue-600 text-white'
                : 'bg-transparent text-gray-400 hover:text-white hover:bg-gray-700',
            )}
            title={label}
          >
            <MIcon name={icon} size={isMobile ? 14 : 16} fill={active ? 1 : 0} />
            <span>{isMobile ? shortLabel : label}</span>
          </button>
        )
      })}
    </div>
  )
}
