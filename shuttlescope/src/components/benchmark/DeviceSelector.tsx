// デバイス選択コンポーネント
// available=true のデバイスのみチェック可。device_type に応じたアイコンを表示。
// specs はツールチップで表示する。

import { Cpu, Monitor, Zap, Network } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ComputeDevice, DeviceType } from '@/api/benchmark'

interface Props {
  devices: ComputeDevice[]
  selected: string[]
  onChange: (ids: string[]) => void
}

/** device_type に対応するアイコンを返す */
function DeviceIcon({ type }: { type: DeviceType }) {
  const cls = 'shrink-0'
  switch (type) {
    case 'cpu':        return <Cpu     size={14} className={cls} />
    case 'igpu':       return <Monitor size={14} className={cls} />
    case 'dgpu':       return <Zap     size={14} className={cls} />
    case 'ray_worker': return <Network size={14} className={cls} />
  }
}

/** specs オブジェクトを人間が読みやすい文字列に変換する */
function formatSpecs(specs: Record<string, string | number>): string {
  return Object.entries(specs)
    .map(([k, v]) => `${k}: ${v}`)
    .join('\n')
}

export function DeviceSelector({ devices, selected, onChange }: Props) {
  const { t } = useTranslation()

  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((x) => x !== id))
    } else {
      onChange([...selected, id])
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-gray-400">{t('benchmark.detect_devices')}</p>
      {devices.length === 0 && (
        <p className="text-xs text-gray-500">{t('benchmark.unavailable')}</p>
      )}
      {devices.map((dev) => {
        const isChecked = selected.includes(dev.device_id)
        const disabled  = !dev.available

        return (
          <label
            key={dev.device_id}
            title={formatSpecs(dev.specs)}
            className={`flex items-center gap-2 px-3 py-2 rounded border text-sm transition-colors cursor-pointer ${
              disabled
                ? 'border-gray-700 text-gray-600 cursor-not-allowed bg-gray-900/30'
                : isChecked
                ? 'border-blue-500 bg-blue-900/20 text-blue-200'
                : 'border-gray-600 bg-gray-800/40 text-gray-300 hover:border-gray-500'
            }`}
          >
            <input
              type="checkbox"
              checked={isChecked}
              disabled={disabled}
              onChange={() => !disabled && toggle(dev.device_id)}
              className="accent-blue-500"
            />
            <DeviceIcon type={dev.device_type} />
            <span className="flex-1">{dev.label}</span>
            <span className="text-[11px] text-gray-500">{t(`benchmark.device_types.${dev.device_type}`)}</span>
            {disabled && (
              <span className="text-[10px] text-gray-600 ml-1">{t('benchmark.unavailable')}</span>
            )}
          </label>
        )
      })}
    </div>
  )
}
