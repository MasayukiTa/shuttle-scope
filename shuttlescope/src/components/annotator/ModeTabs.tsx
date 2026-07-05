/**
 * U2 / UX-R2: AnnotatorPage 上バー左の 4 モードタブ。
 * 入力 / 確認 / 解析 / 設定 を切替。Material Symbols + i18n。
 */
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'

import { MIcon } from '@/components/common/MIcon'
import { AnnotatorMode, useAnnotatorModeStore } from '@/store/annotatorModeStore'

interface TabSpec {
  key: AnnotatorMode
  labelKey: string
  icon: string
}

const TABS: TabSpec[] = [
  { key: 'input',    labelKey: 'annotator.ux.mode_input',    icon: 'edit_note' },
  { key: 'review',   labelKey: 'annotator.ux.mode_review',   icon: 'visibility' },
  { key: 'analysis', labelKey: 'annotator.ux.mode_analysis', icon: 'analytics' },
  { key: 'settings', labelKey: 'annotator.ux.mode_settings', icon: 'settings' },
]

interface ModeTabsProps {
  isMobile?: boolean
  className?: string
}

export function ModeTabs({ isMobile, className }: ModeTabsProps) {
  const { t } = useTranslation()
  const mode = useAnnotatorModeStore((s) => s.mode)
  const setMode = useAnnotatorModeStore((s) => s.setMode)
  return (
    <div
      className={clsx('flex items-center gap-0.5 shrink-0', className)}
      role="tablist"
      aria-label={t('annotator.ux.mode_aria')}
      data-tutorial="annotator.modeTabs"
    >
      {TABS.map(({ key, labelKey, icon }) => {
        const active = mode === key
        const label = t(labelKey)
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => setMode(key)}
            className={clsx(
              'flex items-center gap-1 rounded-ss-md font-medium transition-colors duration-base ease-out',
              isMobile ? 'px-1.5 py-1 text-[10px]' : 'px-2.5 py-1.5 text-xs',
              active
                ? 'bg-[var(--ss-brand)] text-white'
                : 'bg-transparent text-[var(--ss-t2)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-3)]',
            )}
            title={label}
          >
            <MIcon name={icon} size={isMobile ? 14 : 16} fill={active ? 1 : 0} />
            <span>{label}</span>
          </button>
        )
      })}
    </div>
  )
}
