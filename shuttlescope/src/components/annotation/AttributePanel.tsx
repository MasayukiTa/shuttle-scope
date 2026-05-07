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
        className={`flex items-center gap-1.5 px-3 py-2.5 md:px-2 md:py-1 rounded border transition-colors ${
          attributes.is_backhand
            ? 'bg-purple-700 border-purple-500 text-white'
            : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
        } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span>{t('annotator.backhand')} (BH)</span>
        <kbd className="hidden md:inline text-[10px] font-mono opacity-60 bg-black/20 px-1 rounded">Q</kbd>
      </button>

      {/* ラウンドヘッド */}
      <button
        onClick={() => toggle('is_around_head', !attributes.is_around_head)}
        disabled={disabled}
        aria-pressed={attributes.is_around_head}
        aria-disabled={disabled || undefined}
        aria-keyshortcuts="W"
        className={`flex items-center gap-1.5 px-3 py-2.5 md:px-2 md:py-1 rounded border transition-colors ${
          attributes.is_around_head
            ? 'bg-purple-700 border-purple-500 text-white'
            : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
        } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span>{t('annotator.around_head')} (RH)</span>
        <kbd className="hidden md:inline text-[10px] font-mono opacity-60 bg-black/20 px-1 rounded">W</kbd>
      </button>

      {/* ネット上下 */}
      <div
        className="flex items-center gap-1.5 md:gap-1"
        role="radiogroup"
        aria-label={t('annotator.net_position_aria')}
      >
        <span className="text-gray-500 text-xs">
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
                  ? 'px-3 py-2 md:px-2 md:py-0.5 rounded bg-blue-600 text-white text-xs'
                  : 'px-3 py-2 md:px-2 md:py-0.5 rounded bg-gray-700 text-gray-300 text-xs hover:bg-gray-600')
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
