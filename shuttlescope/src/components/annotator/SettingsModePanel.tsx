/**
 * U3/U8 設定モード — JMP 風 カスケーディング Dropdown 階層化。
 *
 *   [カテゴリ ▼: 記録モード]
 *     [項目 ▼: 試合中モード]
 *       [コントロール表示]
 *
 * 全て select 要素で実装。設定項目は数が少なく頻度低いので、Dropdown の
 * 1+1 click 増加コストは許容可能 (連打しない)。
 */
import { ReactNode, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { useAnnotationStore } from '@/store/annotationStore'
import type { StepFocusMode } from '@/store/annotatorModeStore'

interface SettingsModePanelProps {
  isMatchDayMode: boolean
  onToggleMatchDayMode: () => void
  isBasicMode: boolean
  onToggleAnnotationMode: () => void
  onOpenCalibration?: () => void
  onOpenKeyboardLegend?: () => void
  /** UX-R1: 入力モードのステップ連動表示 */
  stepFocusMode?: StepFocusMode
  onSetStepFocusMode?: (m: StepFocusMode) => void
}

interface ItemSpec {
  key: string
  label: string
  render: () => ReactNode
}

interface CategorySpec {
  key: string
  label: string
  icon: string
  items: ItemSpec[]
}

export function SettingsModePanel({
  isMatchDayMode,
  onToggleMatchDayMode,
  isBasicMode,
  onToggleAnnotationMode,
  onOpenCalibration,
  onOpenKeyboardLegend,
  stepFocusMode,
  onSetStepFocusMode,
}: SettingsModePanelProps) {
  const { t } = useTranslation()
  const flipMode = useAnnotationStore((s) => s.flipMode)
  const setFlipMode = useAnnotationStore((s) => s.setFlipMode)

  const categories: CategorySpec[] = useMemo(() => ([
    {
      key: 'mode',
      label: t('annotator.ux.settings_section_mode'),
      icon: 'tune',
      items: [
        {
          key: 'match_day',
          label: t('annotator.ux.settings_match_day_label'),
          render: () => (
            <ToggleControl
              label={t('annotator.ux.settings_match_day_label')}
              hint={t('annotator.ux.settings_match_day_hint')}
              on={isMatchDayMode}
              onClick={onToggleMatchDayMode}
            />
          ),
        },
        {
          key: 'annot_method',
          label: t('annotator.ux.settings_assist_label'),
          render: () => (
            <ToggleControl
              label={t('annotator.ux.settings_assist_label')}
              hint={isBasicMode
                ? t('annotator.ux.settings_assist_hint_basic')
                : t('annotator.ux.settings_assist_hint_assisted')}
              on={!isBasicMode}
              onClick={onToggleAnnotationMode}
            />
          ),
        },
        {
          key: 'step_focus',
          label: t('annotator.ux.settings_step_focus_label'),
          render: () => (
            <div className="space-y-1.5">
              {(['step', 'all'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => onSetStepFocusMode?.(m)}
                  disabled={!onSetStepFocusMode}
                  className={
                    'w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-xs transition-colors ' +
                    (stepFocusMode === m
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50')
                  }
                >
                  <span>{m === 'step'
                    ? t('annotator.ux.settings_step_focus_step')
                    : t('annotator.ux.settings_step_focus_all')}</span>
                  <span className="text-[10px] opacity-70">{m}</span>
                </button>
              ))}
              <p className="text-[10px] text-gray-500 mt-1">
                {t('annotator.ux.settings_step_focus_hint')}
              </p>
            </div>
          ),
        },
      ],
    },
    {
      key: 'flip',
      label: t('annotator.ux.settings_section_flip'),
      icon: 'swap_horiz',
      items: [
        {
          key: 'flip_mode',
          label: t('annotator.ux.settings_section_flip'),
          render: () => (
            <div className="space-y-1.5">
              {(['auto', 'semi-auto', 'manual'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setFlipMode(m)}
                  className={
                    'w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-xs transition-colors ' +
                    (flipMode === m
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-200 hover:bg-gray-600')
                  }
                >
                  <span>{labelForFlip(m, t)}</span>
                  <span className="text-[10px] opacity-70">{m}</span>
                </button>
              ))}
              <p className="text-[10px] text-gray-500 mt-1">
                {t('annotator.ux.settings_flip_hint')}
              </p>
            </div>
          ),
        },
      ],
    },
    {
      key: 'court',
      label: t('annotator.ux.settings_section_court'),
      icon: 'crop_square',
      items: [
        {
          key: 'open',
          label: t('annotator.ux.settings_section_court'),
          render: () => (
            <button
              type="button"
              onClick={onOpenCalibration}
              disabled={!onOpenCalibration}
              className="w-full px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {t('annotator.ux.settings_court_open')}
            </button>
          ),
        },
      ],
    },
    {
      key: 'keys',
      label: t('annotator.ux.settings_section_keys'),
      icon: 'keyboard',
      items: [
        {
          key: 'legend',
          label: t('annotator.ux.settings_section_keys'),
          render: () => (
            <button
              type="button"
              onClick={onOpenKeyboardLegend}
              disabled={!onOpenKeyboardLegend}
              className="w-full px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {t('annotator.ux.settings_keys_legend')}
            </button>
          ),
        },
      ],
    },
  ]), [
    t, isMatchDayMode, onToggleMatchDayMode, isBasicMode, onToggleAnnotationMode,
    flipMode, setFlipMode, onOpenCalibration, onOpenKeyboardLegend,
    stepFocusMode, onSetStepFocusMode,
  ])

  const [categoryKey, setCategoryKey] = useState(categories[0].key)
  const category = categories.find((c) => c.key === categoryKey) ?? categories[0]
  const [itemKey, setItemKey] = useState(category.items[0].key)
  const item = category.items.find((i) => i.key === itemKey) ?? category.items[0]

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="flex items-center gap-2 px-3 py-2 text-sm font-medium border-b border-gray-700 shrink-0 bg-gray-800/40 text-gray-200">
        <MIcon name="settings" size={18} />
        {t('annotator.ux.settings_header')}
      </header>

      <div className="px-3 py-3 space-y-3 text-xs">
        {/* Level 1: Category dropdown */}
        <DropdownRow
          label={t('annotator.ux.settings_category')}
          icon={category.icon}
          value={categoryKey}
          onChange={(v) => {
            setCategoryKey(v)
            const next = categories.find((c) => c.key === v)
            if (next) setItemKey(next.items[0].key)
          }}
          options={categories.map((c) => ({ value: c.key, label: c.label }))}
        />

        {/* Level 2: Item dropdown (within category) */}
        <DropdownRow
          label={t('annotator.ux.settings_item')}
          icon="list"
          value={itemKey}
          onChange={setItemKey}
          options={category.items.map((i) => ({ value: i.key, label: i.label }))}
        />

        {/* Level 3: Control */}
        <div className="border-t border-gray-700 pt-3">
          {item.render()}
        </div>
      </div>
    </div>
  )
}

interface DropdownRowProps {
  label: string
  icon: string
  value: string
  onChange: (v: string) => void
  options: Array<{ value: string; label: string }>
}

function DropdownRow({ label, icon, value, onChange, options }: DropdownRowProps) {
  return (
    <label className="flex items-center gap-2">
      <MIcon name={icon} size={16} className="text-gray-500" />
      <span className="text-[11px] text-gray-400 w-16 shrink-0">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 bg-gray-800 text-gray-100 border border-gray-700 rounded px-2 py-1 text-xs"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  )
}

function ToggleControl({
  label, hint, on, onClick,
}: { label: string; hint?: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-between gap-2 px-2 py-2 rounded bg-gray-700 hover:bg-gray-600 text-left text-gray-200"
    >
      <span className="flex flex-col">
        <span>{label}</span>
        {hint && <span className="text-[10px] text-gray-400">{hint}</span>}
      </span>
      <span
        className={
          'text-[10px] px-1.5 py-0.5 rounded font-mono ' +
          (on ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400')
        }
      >
        {on ? 'ON' : 'OFF'}
      </span>
    </button>
  )
}

function labelForFlip(m: 'auto' | 'semi-auto' | 'manual', t: (k: string) => string): string {
  if (m === 'auto') return t('annotator.ux.settings_flip_auto')
  if (m === 'semi-auto') return t('annotator.ux.settings_flip_semi')
  return t('annotator.ux.settings_flip_manual')
}
