import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { ShotType } from '@/types'

interface ShotTypePanelProps {
  selected: ShotType | null
  onSelect: (shotType: ShotType) => void
  disabled?: boolean
}

// ショット種別のキーボードショートカットマップ
const KEYBOARD_MAP: Record<string, ShotType> = {
  '1': 'short_service', '2': 'long_service',
  'n': 'net_shot', 'c': 'clear', 'p': 'push_rush',
  's': 'smash', 'd': 'defensive', 'v': 'drive',
  'l': 'lob', 'o': 'drop', 'x': 'cross_net',
  'z': 'slice', 'a': 'around_head', 'q': 'cant_reach',
  'f': 'flick', 'h': 'half_smash', 'b': 'block', '0': 'other',
}

// ショット種別のカテゴリグループ
const SHOT_GROUPS: { labelKey: string; shots: Array<{ type: ShotType; key: string }> }[] = [
  {
    labelKey: 'shot_categories.serve',
    shots: [
      { type: 'short_service', key: '1' },
      { type: 'long_service', key: '2' },
    ],
  },
  {
    labelKey: 'shot_categories.net',
    shots: [
      { type: 'net_shot', key: 'N' },
      { type: 'push_rush', key: 'P' },
      { type: 'cross_net', key: 'X' },
    ],
  },
  {
    labelKey: 'shot_categories.back',
    shots: [
      { type: 'clear', key: 'C' },
      { type: 'smash', key: 'S' },
      { type: 'drop', key: 'O' },
      { type: 'slice', key: 'Z' },
      { type: 'around_head', key: 'A' },
    ],
  },
  {
    labelKey: 'shot_categories.mid',
    shots: [
      { type: 'drive', key: 'V' },
      { type: 'lob', key: 'L' },
      { type: 'defensive', key: 'D' },
      { type: 'flick', key: 'F' },
      { type: 'half_smash', key: 'H' },
      { type: 'block', key: 'B' },
    ],
  },
  {
    labelKey: 'shot_categories.special',
    shots: [
      { type: 'cant_reach', key: 'Q' },
      { type: 'other', key: '0' },
    ],
  },
]

export function ShotTypePanel({ selected, onSelect, disabled = false }: ShotTypePanelProps) {
  const { t } = useTranslation()

  return (
    <div className="flex flex-col gap-2">
      {SHOT_GROUPS.map((group) => (
        <div key={group.labelKey}>
          <div className="text-xs text-gray-500 mb-1 px-1">{t(group.labelKey)}</div>
          <div className="grid grid-cols-3 gap-1">
            {group.shots.map(({ type, key }) => (
              <button
                key={type}
                onClick={() => !disabled && onSelect(type)}
                disabled={disabled}
                className={clsx(
                  'relative px-2 py-1.5 rounded text-xs font-medium transition-colors',
                  selected === type
                    ? 'bg-blue-600 text-white border border-blue-400'
                    : 'bg-gray-700 text-gray-200 border border-gray-600 hover:bg-gray-600',
                  disabled && 'opacity-40 cursor-not-allowed'
                )}
                title={`${t(`shot_types.${type}`)} (${key})`}
              >
                {/* キーボードショートカット表示 */}
                <span className="absolute top-0.5 right-1 text-[9px] opacity-60 font-mono">{key}</span>
                <span className="block text-center leading-tight">{t(`shot_types.${type}`)}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export { KEYBOARD_MAP }
