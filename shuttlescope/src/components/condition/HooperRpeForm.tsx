import { useTranslation } from 'react-i18next'
import { ConditionPayload } from '@/hooks/useConditions'

// Hooper Index (1-7) と Session RPE (0-10) の入力。
// サーバが hooper_index (合計) と session_load (RPE * duration) を自動計算する。
type HooperKey = 'hooper_sleep' | 'hooper_soreness' | 'hooper_stress' | 'hooper_fatigue'

const HOOPER_FIELDS: { key: HooperKey; labelKey: string }[] = [
  { key: 'hooper_sleep',    labelKey: 'condition.hooper.sleep' },
  { key: 'hooper_soreness', labelKey: 'condition.hooper.soreness' },
  { key: 'hooper_stress',   labelKey: 'condition.hooper.stress' },
  { key: 'hooper_fatigue',  labelKey: 'condition.hooper.fatigue' },
]

interface Props {
  value: Partial<ConditionPayload>
  onChange: (patch: Partial<ConditionPayload>) => void
  isLight?: boolean
}

export function HooperRpeForm({ value, onChange, isLight }: Props) {
  const { t } = useTranslation()
  const inputCls = isLight
    ? 'w-full border border-gray-300 bg-white text-gray-900 rounded px-2 py-1.5'
    : 'w-full border border-gray-600 bg-gray-800 text-white rounded px-2 py-1.5'
  const labelCls = isLight ? 'text-xs text-gray-600' : 'text-xs text-gray-400'

  const setNum = (k: keyof ConditionPayload, raw: string) => {
    onChange({ [k]: raw === '' ? null : Number(raw) } as Partial<ConditionPayload>)
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {HOOPER_FIELDS.map(({ key, labelKey }) => {
          const v = value[key] as number | null | undefined
          return (
            <label key={key} className="flex flex-col gap-1">
              <span className={labelCls}>{t(labelKey)}</span>
              <select
                className={inputCls}
                value={v ?? ''}
                onChange={(e) => setNum(key, e.target.value)}
              >
                <option value="">—</option>
                {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
          )
        })}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>{t('condition.rpe.session_rpe')}</span>
          <input
            type="number"
            min={0}
            max={10}
            step="0.5"
            inputMode="decimal"
            className={inputCls}
            value={value.session_rpe ?? ''}
            onChange={(e) => setNum('session_rpe', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>{t('condition.rpe.session_duration_min')}</span>
          <input
            type="number"
            min={0}
            step="1"
            inputMode="numeric"
            className={inputCls}
            value={value.session_duration_min ?? ''}
            onChange={(e) => setNum('session_duration_min', e.target.value)}
          />
        </label>
      </div>
    </div>
  )
}
