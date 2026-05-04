/**
 * DateRangeFilter — 期間フィルター
 *
 * 試合一覧等で日付範囲による絞り込みに使用。
 * プリセット（直近1ヶ月、3ヶ月、半年、1年、全期間）+ カスタム日付入力。
 */
import { useState } from 'react'
import { Calendar } from 'lucide-react'
import { clsx } from 'clsx'

interface DateRangeFilterProps {
  from: string
  to: string
  onChange: (from: string, to: string) => void
  className?: string
}

type Preset = '1m' | '3m' | '6m' | '1y' | 'all'

function computePresetFrom(preset: Preset): string {
  if (preset === 'all') return ''
  const d = new Date()
  switch (preset) {
    case '1m': d.setMonth(d.getMonth() - 1); break
    case '3m': d.setMonth(d.getMonth() - 3); break
    case '6m': d.setMonth(d.getMonth() - 6); break
    case '1y': d.setFullYear(d.getFullYear() - 1); break
  }
  return d.toISOString().split('T')[0]
}

function detectPreset(from: string): Preset | null {
  if (!from) return 'all'
  const presets: Preset[] = ['1m', '3m', '6m', '1y']
  for (const p of presets) {
    if (computePresetFrom(p) === from) return p
  }
  return null
}

const PRESET_LABELS: Record<Preset, string> = {
  '1m': '1ヶ月',
  '3m': '3ヶ月',
  '6m': '半年',
  '1y': '1年',
  'all': '全期間',
}

export function DateRangeFilter({ from, to, onChange, className }: DateRangeFilterProps) {
  const [showCustom, setShowCustom] = useState(false)
  const activePreset = detectPreset(from)

  const handlePreset = (p: Preset) => {
    setShowCustom(false)
    onChange(computePresetFrom(p), '')
  }

  return (
    <div className={clsx('flex items-center gap-1.5 flex-wrap', className)}>
      <Calendar size={13} className="text-gray-500 shrink-0" />
      {(Object.entries(PRESET_LABELS) as [Preset, string][]).map(([key, label]) => (
        <button
          key={key}
          onClick={() => handlePreset(key)}
          className={clsx(
            'px-2 py-0.5 rounded text-xs transition-colors',
            activePreset === key && !showCustom
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-400 hover:text-white hover:bg-gray-600',
          )}
        >
          {label}
        </button>
      ))}
      <button
        onClick={() => setShowCustom((v) => !v)}
        className={clsx(
          'px-2 py-0.5 rounded text-xs transition-colors',
          showCustom
            ? 'bg-blue-600 text-white'
            : 'bg-gray-700 text-gray-400 hover:text-white hover:bg-gray-600',
        )}
      >
        期間指定
      </button>
      {showCustom && (
        <div className="flex items-center gap-1 text-xs">
          <input
            type="date"
            value={from}
            onChange={(e) => onChange(e.target.value, to)}
            className="bg-gray-700 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-white"
          />
          <span className="text-gray-500">〜</span>
          <input
            type="date"
            value={to}
            onChange={(e) => onChange(from, e.target.value)}
            className="bg-gray-700 border border-gray-600 rounded px-1.5 py-0.5 text-xs text-white"
          />
        </div>
      )}
    </div>
  )
}
