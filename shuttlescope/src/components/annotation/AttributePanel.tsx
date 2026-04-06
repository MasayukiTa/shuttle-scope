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
      <button
        onClick={() => toggle('is_backhand', !attributes.is_backhand)}
        disabled={disabled}
        className={`flex items-center gap-1.5 px-2 py-1 rounded border transition-colors ${
          attributes.is_backhand
            ? 'bg-purple-700 border-purple-500 text-white'
            : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
        } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span>{t('annotator.backhand')} (BH)</span>
        <kbd className="text-[10px] font-mono opacity-60 bg-black/20 px-1 rounded">Q</kbd>
        <kbd className="text-[10px] font-mono opacity-40 bg-black/20 px-1 rounded">Num/</kbd>
      </button>

      {/* ラウンドヘッド */}
      <button
        onClick={() => toggle('is_around_head', !attributes.is_around_head)}
        disabled={disabled}
        className={`flex items-center gap-1.5 px-2 py-1 rounded border transition-colors ${
          attributes.is_around_head
            ? 'bg-purple-700 border-purple-500 text-white'
            : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600'
        } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span>{t('annotator.around_head')} (RH)</span>
        <kbd className="text-[10px] font-mono opacity-60 bg-black/20 px-1 rounded">W</kbd>
        <kbd className="text-[10px] font-mono opacity-40 bg-black/20 px-1 rounded">Num*</kbd>
      </button>

      {/* ネット上下 */}
      <div className="flex items-center gap-1">
        <span className="text-gray-500 text-xs">
          ネット <kbd className="text-[10px] font-mono opacity-60 bg-gray-700 px-1 rounded">E</kbd><kbd className="text-[10px] font-mono opacity-40 bg-gray-700 px-1 rounded">Num−</kbd>:
        </span>
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
