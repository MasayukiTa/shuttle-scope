// デバイス選択コンポーネント
// available=true のデバイスのみチェック可。device_type に応じたアイコンを表示。
// specs はツールチップで表示する。

import { useTranslation } from 'react-i18next'
import { ComputeDevice, DeviceType } from '@/api/benchmark'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  devices: ComputeDevice[]
  selected: string[]
  onChange: (ids: string[]) => void
}

/** device_type に対応するアイコンを返す */
function DeviceIcon({ type }: { type: DeviceType }) {
  const cls = 'shrink-0'
  switch (type) {
    case 'cpu':        return <MIcon name="memory"     size={14} className={cls} />
    case 'igpu':       return <MIcon name="monitor" size={14} className={cls} />
    case 'dgpu':       return <MIcon name="bolt"     size={14} className={cls} />
    case 'ray_worker': return <MIcon name="lan" size={14} className={cls} />
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
      <p className="text-xs font-medium text-[var(--ss-t2)]">{t('benchmark.detect_devices')}</p>
      {devices.length === 0 && (
        <p className="text-xs text-[var(--ss-t3)]">{t('benchmark.unavailable')}</p>
      )}
      {devices.map((dev) => {
        const isChecked = selected.includes(dev.device_id)
        const disabled  = !dev.available

        return (
          <label
            key={dev.device_id}
            title={formatSpecs(dev.specs)}
            className={`flex items-center gap-2 px-3 py-2 rounded-ss-md border text-sm transition-colors cursor-pointer ${
              disabled
                ? 'border-[var(--ss-border)] text-[var(--ss-t3)] cursor-not-allowed bg-[var(--ss-surface-3)]'
                : isChecked
                ? 'border-[var(--ss-brand)] bg-[var(--ss-brand)] text-white'
                : 'border-[var(--ss-border)] bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:border-[var(--ss-brand)]'
            }`}
          >
            <input
              type="checkbox"
              checked={isChecked}
              disabled={disabled}
              onChange={() => !disabled && toggle(dev.device_id)}
              className="accent-[var(--ss-brand)]"
            />
            <DeviceIcon type={dev.device_type} />
            <span className="flex-1">{dev.label}</span>
            <span className={`text-[11px] ${isChecked ? 'text-white' : 'text-[var(--ss-t3)]'}`}>{t(`benchmark.device_types.${dev.device_type}`)}</span>
            {disabled && (
              <span className="text-[10px] text-[var(--ss-t3)] ml-1">{t('benchmark.unavailable')}</span>
            )}
          </label>
        )
      })}
    </div>
  )
}
