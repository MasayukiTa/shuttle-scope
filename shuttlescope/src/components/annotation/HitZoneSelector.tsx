/**
 * HitZoneSelector — 打点 (hit_zone) 9-zone マニュアル override パネル
 *
 * Phase A 実装（hybrid_ui_implementation_plan_v2.md §6 参照）。
 *
 * 仕様:
 *   - 3x3 grid, 各セル最小 64x64dp
 *   - cvPrediction が指定されていれば該当セルに ✨ アイコン付きで preselect
 *   - selectedZone はユーザの最終選択（CV と同値なら border のみハイライト、
 *     違うなら太枠 + 別色で「override 済」を明示）
 *   - 1 タップで onZoneSelect 発火
 *
 * 状態機械への介入なし: AnnotatorPage 側で inputStep === 'land_zone' の
 * レンダ内に並列追加するだけ。
 */
import { clsx } from 'clsx'
import { useTranslation } from 'react-i18next'
import { Zone9 } from '@/types'
import { MIcon } from '@/components/common/MIcon'

interface HitZoneSelectorProps {
  /** CV 自動推定値 (1-9), null = 推定なし */
  cvPrediction: Zone9 | null
  /** 現在の選択値 (override 後 or CV 値) */
  selectedZone: Zone9 | null
  /** タップ callback。Zone9 数字を渡す */
  onZoneSelect: (zone: Zone9) => void
  /** 人間が override したかどうか（border 強調用） */
  isOverridden: boolean
  /** 入力不可状態 */
  disabled?: boolean
  /** タイル一辺サイズ (px)。デフォルト 60 */
  cellSize?: number
}

const ZONES: Zone9[] = [1, 2, 3, 4, 5, 6, 7, 8, 9]

export function HitZoneSelector({
  cvPrediction,
  selectedZone,
  onZoneSelect,
  isOverridden,
  disabled = false,
  cellSize = 60,
}: HitZoneSelectorProps) {
  const { t } = useTranslation()

  return (
    <div className="flex flex-col items-center gap-1" data-tutorial="annotator.hitZone">
      <div className="text-xs font-medium text-[var(--ss-brand)] flex items-center gap-1">
        <span>{t('annotator.hit_zone')}</span>
        {isOverridden && (
          // 旧: text-[10px] で WCAG AA 失敗 (小文字 + orange-400 on dark = ~3.5:1)
          // 新: text-xs (12px) + var(--ss-emphasis) + 丸枠で視認性確保
          <span
            className="inline-flex items-center px-1 py-0.5 rounded-ss-sm border border-[var(--ss-border)] bg-[var(--ss-surface-2)] text-xs text-[var(--ss-emphasis)] font-semibold leading-none"
            aria-label={t('annotator.hit_zone_overridden')}
          >
            <MIcon name="edit" size={11} aria-hidden /> {t('annotator.hit_zone_overridden')}
          </span>
        )}
      </div>
      <div
        className="grid grid-cols-3 gap-1.5"
        role="grid"
        aria-label={t('annotator.hit_zone_aria')}
      >
        {ZONES.map((zone) => {
          const isCv = cvPrediction === zone
          const isSelected = selectedZone === zone
          const isManualPick = isSelected && isOverridden
          const isCvMatch = isSelected && !isOverridden && isCv

          return (
            <button
              key={zone}
              type="button"
              data-tile="hit-zone"
              onClick={() => !disabled && onZoneSelect(zone)}
              disabled={disabled}
              aria-pressed={isSelected}
              aria-label={t('annotator.hit_zone_cell', { zone })}
              className={clsx(
                'relative flex items-center justify-center rounded-ss-md font-mono ss-num text-base font-bold',
                'transition-colors duration-100 select-none',
                isManualPick
                  ? 'bg-[var(--ss-emphasis)] text-white border-2 border-[var(--ss-emphasis)]'
                  : isCvMatch
                    ? 'bg-[var(--ss-brand)] text-white border-2 border-[var(--ss-brand)]'
                    : isCv
                      ? 'bg-[var(--ss-surface-2)] text-[var(--ss-brand)] border border-[var(--ss-border-strong)]'
                      : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] border border-[var(--ss-border)] hover:bg-[var(--ss-surface-3)]',
                disabled && 'opacity-40 cursor-not-allowed',
              )}
              style={{
                // iOS フォント縮小耐性: globals.css の data-tile="hit-zone" が
                // 44x44 を確保するため、cellSize はそれを下回らないよう Math.max
                minWidth: Math.max(cellSize, 44),
                minHeight: Math.max(cellSize, 44),
              }}
            >
              <span>{zone}</span>
              {isCv && (
                <MIcon name="auto_awesome"
                  size={10}
                  className="absolute top-0.5 right-0.5 text-[var(--ss-warn)]"
                  aria-hidden
                />
              )}
            </button>
          )
        })}
      </div>
      {cvPrediction != null && (
        <div className="text-[10px] ss-num text-[var(--ss-t3)]">
          {t('annotator.hit_zone_cv_label', { zone: cvPrediction })}
        </div>
      )}
    </div>
  )
}
