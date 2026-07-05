import { useTranslation } from 'react-i18next'
import { StrokeAttributes } from '@/types'

interface AttributePanelProps {
  attributes: StrokeAttributes
  onChange: (attrs: StrokeAttributes) => void
  disabled?: boolean
}

/**
 * ストローク属性パネル（BH/AH/ネット上下）
 * モバイル: 大きめタッチターゲット、キーボードヒント非表示
 */
export function AttributePanel({ attributes, onChange, disabled = false }: AttributePanelProps) {
  const { t } = useTranslation()

  const toggle = (key: keyof StrokeAttributes, value: unknown) => {
    if (disabled) return
    onChange({ ...attributes, [key]: value })
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2 md:gap-3 text-sm"
      role="group"
      aria-label={t('annotator.attributes_aria')}
      aria-disabled={disabled || undefined}
    >
      {/* バックハンド */}
      <button
        onClick={() => toggle('is_backhand', !attributes.is_backhand)}
        disabled={disabled}
        aria-pressed={attributes.is_backhand}
        aria-disabled={disabled || undefined}
        aria-keyshortcuts="Q"
        className={`flex items-center gap-1.5 px-3 py-2.5 md:px-2 md:py-1 rounded-ss-md border transition-colors duration-fast ease-out ${
          attributes.is_backhand
            ? 'bg-[var(--ss-brand)] border-[var(--ss-brand)] text-white'
            : 'bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]'
        } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span>{t('annotator.backhand')} {t('auto.AttributePanel.bh')}</span>
        <kbd className="hidden md:inline text-[10px] font-mono ss-num opacity-60 bg-[var(--ss-surface-3)] px-1 rounded-ss-sm">Q</kbd>
      </button>

      {/* ラウンドヘッド */}
      <button
        onClick={() => toggle('is_around_head', !attributes.is_around_head)}
        disabled={disabled}
        aria-pressed={attributes.is_around_head}
        aria-disabled={disabled || undefined}
        aria-keyshortcuts="W"
        className={`flex items-center gap-1.5 px-3 py-2.5 md:px-2 md:py-1 rounded-ss-md border transition-colors duration-fast ease-out ${
          attributes.is_around_head
            ? 'bg-[var(--ss-brand)] border-[var(--ss-brand)] text-white'
            : 'bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]'
        } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span>{t('annotator.around_head')} {t('auto.AttributePanel.rh')}</span>
        <kbd className="hidden md:inline text-[10px] font-mono ss-num opacity-60 bg-[var(--ss-surface-3)] px-1 rounded-ss-sm">W</kbd>
      </button>

      {/* ネット上下 */}
      <div
        className="flex items-center gap-1.5 md:gap-1"
        role="radiogroup"
        aria-label={t('annotator.net_position_aria')}
      >
        <span className="text-[var(--ss-t3)] text-xs">
          {t('annotator.net_label')}
        </span>
        {[
          { value: true, label: t('annotator.above_net') },
          { value: false, label: t('annotator.below_net') },
          { value: undefined, label: t('annotator.net_unknown') },
        ].map(({ value, label }) => {
          const selected = attributes.above_net === value
          return (
            <button
              key={String(value)}
              onClick={() => toggle('above_net', value)}
              disabled={disabled}
              role="radio"
              aria-checked={selected}
              aria-disabled={disabled || undefined}
              className={
                (selected
                  ? 'px-3 py-2 md:px-2 md:py-0.5 rounded-ss-md bg-[var(--ss-brand)] text-white text-xs transition-colors duration-fast ease-out'
                  : 'px-3 py-2 md:px-2 md:py-0.5 rounded-ss-md bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] text-[var(--ss-t2)] text-xs hover:bg-[var(--ss-surface-3)] transition-colors duration-fast ease-out')
                + (disabled ? ' opacity-40 cursor-not-allowed' : '')
              }
            >
              {label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
