import { useTranslation } from 'react-i18next'
import { StrokeAttributes } from '@/types'

interface AttributePanelProps {
  attributes: StrokeAttributes
  onChange: (attrs: StrokeAttributes) => void
  disabled?: boolean
}

/**
 * ストローク属性パネル（BH/AH/ネット上下）
 */
export function AttributePanel({ attributes, onChange, disabled = false }: AttributePanelProps) {
  const { t } = useTranslation()

  const toggle = (key: keyof StrokeAttributes, value: unknown) => {
    if (disabled) return
    onChange({ ...attributes, [key]: value })
  }

  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      {/* バックハンド */}
      <label className="flex items-center gap-1 cursor-pointer">
        <input
          type="checkbox"
          checked={attributes.is_backhand}
          onChange={(e) => toggle('is_backhand', e.target.checked)}
          disabled={disabled}
          className="w-4 h-4 rounded"
        />
        <span className="text-gray-300">{t('annotator.backhand')} (BH)</span>
      </label>

      {/* ラウンドヘッド */}
      <label className="flex items-center gap-1 cursor-pointer">
        <input
          type="checkbox"
          checked={attributes.is_around_head}
          onChange={(e) => toggle('is_around_head', e.target.checked)}
          disabled={disabled}
          className="w-4 h-4 rounded"
        />
        <span className="text-gray-300">{t('annotator.around_head')} (AH)</span>
      </label>

      {/* ネット上下 */}
      <div className="flex items-center gap-1">
        <span className="text-gray-500 text-xs">ネット:</span>
        {[
          { value: true, label: t('annotator.above_net') },
          { value: false, label: t('annotator.below_net') },
          { value: undefined, label: t('annotator.net_unknown') },
        ].map(({ value, label }) => (
          <button
            key={String(value)}
            onClick={() => toggle('above_net', value)}
            disabled={disabled}
            className={
              attributes.above_net === value
                ? 'px-2 py-0.5 rounded bg-blue-600 text-white text-xs'
                : 'px-2 py-0.5 rounded bg-gray-700 text-gray-300 text-xs hover:bg-gray-600'
            }
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
