/**
 * U3/U8 設定モード — フラットなセクション縦リスト。
 *
 * 旧版は category → item → control の 3 段カスケード Dropdown だったが、
 * 項目総数 10 件未満で 2-click アクセスは試合中の不快感を生んでいた。
 * 1-click でアクセスできるよう、md+ では全セクション展開、md 未満 (BottomSheet
 * 内表示) ではアコーディオンで折り畳む。
 *
 * セクション:
 *   - 記録モード   (試合中モード / 詳細記録 / step focus)
 *   - 自動切替    (flip mode)
 *   - コート      (キャリブレーション起動)
 *   - キーボード   (legend 起動)
 */
import { ReactNode, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { useAnnotationStore } from '@/store/annotationStore'
import { useBreakpoint } from '@/hooks/useBreakpoint'
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
  /** 視点切替: player_a が画面のどちら側に居るか (ユーザ設定値、コートチェンジ前の初期側) */
  playerAStart?: 'top' | 'bottom'
  onSetPlayerAStart?: (side: 'top' | 'bottom') => void
  /** 最初のサーバー (player_a / player_b) */
  initialServer?: 'player_a' | 'player_b'
  onSetInitialServer?: (server: 'player_a' | 'player_b') => void
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
  playerAStart,
  onSetPlayerAStart,
  initialServer,
  onSetInitialServer,
}: SettingsModePanelProps) {
  const { t } = useTranslation()
  const flipMode = useAnnotationStore((s) => s.flipMode)
  const setFlipMode = useAnnotationStore((s) => s.setFlipMode)

  // md+ (タブレット以上) は全セクション常時展開、md 未満は最初の 1 つだけ展開
  const { atLeast } = useBreakpoint()
  const isWide = atLeast('md')

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="flex items-center gap-2 px-3 py-2 text-sm font-medium border-b border-gray-700 shrink-0 bg-gray-800/40 text-gray-200">
        <MIcon name="settings" size={18} />
        {t('annotator.ux.settings_header')}
      </header>

      <div className="px-3 py-3 space-y-2 text-xs">
        <Section
          icon="tune"
          title={t('annotator.ux.settings_section_mode')}
          defaultOpen
          alwaysOpen={isWide}
        >
          <ToggleControl
            label={t('annotator.ux.settings_match_day_label')}
            hint={t('annotator.ux.settings_match_day_hint')}
            on={isMatchDayMode}
            onClick={onToggleMatchDayMode}
          />
          <ToggleControl
            label={t('annotator.ux.settings_assist_label')}
            hint={isBasicMode
              ? t('annotator.ux.settings_assist_hint_basic')
              : t('annotator.ux.settings_assist_hint_assisted')}
            on={!isBasicMode}
            onClick={onToggleAnnotationMode}
          />
          <SegmentedControl
            label={t('annotator.ux.settings_step_focus_label')}
            hint={t('annotator.ux.settings_step_focus_hint')}
            value={stepFocusMode ?? 'all'}
            options={[
              { value: 'step', label: t('annotator.ux.settings_step_focus_step') },
              { value: 'all', label: t('annotator.ux.settings_step_focus_all') },
            ]}
            onChange={(v) => onSetStepFocusMode?.(v as StepFocusMode)}
            disabled={!onSetStepFocusMode}
          />
        </Section>

        <Section
          icon="swap_horiz"
          title={t('annotator.ux.settings_section_flip')}
          alwaysOpen={isWide}
        >
          <SegmentedControl
            label={t('annotator.ux.settings_section_flip')}
            hint={t('annotator.ux.settings_flip_hint')}
            value={flipMode}
            options={[
              { value: 'auto', label: labelForFlip('auto', t) },
              { value: 'semi-auto', label: labelForFlip('semi-auto', t) },
              { value: 'manual', label: labelForFlip('manual', t) },
            ]}
            onChange={(v) => setFlipMode(v as 'auto' | 'semi-auto' | 'manual')}
          />
        </Section>

        {/* 試合設定: 視点 / 最初のサーバー — モバイル & 試合中モードでも到達可能に */}
        {(onSetPlayerAStart || onSetInitialServer) && (
          <Section
            icon="sports_tennis"
            title={t('annotator.ux.settings_section_match')}
            alwaysOpen={isWide}
          >
            {onSetPlayerAStart && (
              <SegmentedControl
                label={t('annotator.ux.settings_player_a_start_label')}
                hint={t('annotator.ux.settings_player_a_start_hint')}
                value={playerAStart ?? 'bottom'}
                options={[
                  { value: 'bottom', label: t('annotator.ux.settings_side_bottom') },
                  { value: 'top', label: t('annotator.ux.settings_side_top') },
                ]}
                onChange={(v) => onSetPlayerAStart(v as 'top' | 'bottom')}
              />
            )}
            {onSetInitialServer && (
              <SegmentedControl
                label={t('annotator.ux.settings_initial_server_label')}
                hint={t('annotator.ux.settings_initial_server_hint')}
                value={initialServer ?? 'player_a'}
                options={[
                  { value: 'player_a', label: 'A' },
                  { value: 'player_b', label: 'B' },
                ]}
                onChange={(v) => onSetInitialServer(v as 'player_a' | 'player_b')}
              />
            )}
          </Section>
        )}

        <Section
          icon="crop_square"
          title={t('annotator.ux.settings_section_court')}
          alwaysOpen={isWide}
        >
          <button
            type="button"
            onClick={onOpenCalibration}
            disabled={!onOpenCalibration}
            className="w-full px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('annotator.ux.settings_court_open')}
          </button>
        </Section>

        <Section
          icon="keyboard"
          title={t('annotator.ux.settings_section_keys')}
          alwaysOpen={isWide}
        >
          <button
            type="button"
            onClick={onOpenKeyboardLegend}
            disabled={!onOpenKeyboardLegend}
            className="w-full px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('annotator.ux.settings_keys_legend')}
          </button>
        </Section>
      </div>
    </div>
  )
}

// ─── Section: md+ では常時展開、md 未満ではアコーディオン ─────────────────────

interface SectionProps {
  icon: string
  title: string
  children: ReactNode
  /** モバイルアコーディオンの初期 open 状態 */
  defaultOpen?: boolean
  /** md+ で強制的に open にする (タブレット/PC は常時展開) */
  alwaysOpen?: boolean
}

function Section({ icon, title, children, defaultOpen = false, alwaysOpen = false }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  const expanded = alwaysOpen || open

  return (
    <div className="rounded border border-gray-700 bg-gray-800/40 overflow-hidden">
      <button
        type="button"
        onClick={() => !alwaysOpen && setOpen((v) => !v)}
        disabled={alwaysOpen}
        aria-expanded={expanded}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left text-gray-200 hover:bg-gray-700/40 disabled:cursor-default disabled:hover:bg-transparent"
      >
        <MIcon name={icon} size={14} className="text-gray-500 shrink-0" />
        <span className="flex-1 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
          {title}
        </span>
        {!alwaysOpen && (
          <MIcon name={expanded ? 'expand_less' : 'expand_more'} size={14} className="text-gray-500" />
        )}
      </button>
      {expanded && (
        <div className="px-2 py-2 space-y-1.5 border-t border-gray-700 bg-gray-900/40">
          {children}
        </div>
      )}
    </div>
  )
}

// ─── ToggleControl: ON/OFF のシンプルトグル ──────────────────────────────────

function ToggleControl({
  label, hint, on, onClick,
}: { label: string; hint?: string; on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-between gap-2 px-2 py-2 rounded bg-gray-700 hover:bg-gray-600 text-left text-gray-200"
    >
      <span className="flex flex-col min-w-0">
        <span className="truncate">{label}</span>
        {hint && <span className="text-[10px] text-gray-400 truncate">{hint}</span>}
      </span>
      <span
        className={
          'text-[10px] px-1.5 py-0.5 rounded font-mono shrink-0 ' +
          (on ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400')
        }
      >
        {on ? 'ON' : 'OFF'}
      </span>
    </button>
  )
}

// ─── SegmentedControl: 3-4 値の固定選択肢 ────────────────────────────────────

interface SegmentedOption {
  value: string
  label: string
}

function SegmentedControl({
  label, hint, value, options, onChange, disabled,
}: {
  label: string
  hint?: string
  value: string
  options: SegmentedOption[]
  onChange: (v: string) => void
  disabled?: boolean
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-gray-400">{label}</span>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            disabled={disabled}
            className={
              'px-2 py-1.5 rounded text-xs transition-colors truncate ' +
              (value === o.value
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50')
            }
          >
            {o.label}
          </button>
        ))}
      </div>
      {hint && <span className="text-[10px] text-gray-500">{hint}</span>}
    </div>
  )
}

function labelForFlip(m: 'auto' | 'semi-auto' | 'manual', t: (k: string) => string): string {
  if (m === 'auto') return t('annotator.ux.settings_flip_auto')
  if (m === 'semi-auto') return t('annotator.ux.settings_flip_semi')
  return t('annotator.ux.settings_flip_manual')
}
