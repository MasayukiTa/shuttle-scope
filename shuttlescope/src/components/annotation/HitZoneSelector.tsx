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
import { Sparkles } from 'lucide-react'

import { Zone9 } from '@/types'

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
    <div className="flex flex-col items-center gap-1">
      <div className="text-xs font-medium text-blue-300">
        {t('annotator.hit_zone')} {isOverridden && (
          <span className="ml-1 text-[10px] text-orange-400">({t('annotator.hit_zone_overridden')})</span>
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
                'relative flex items-center justify-center rounded font-mono text-base font-bold',
                'transition-all duration-100 select-none',
                isManualPick
                  ? 'bg-orange-500 text-white border-2 border-orange-300 shadow-lg shadow-orange-500/40'
                  : isCvMatch
                    ? 'bg-blue-600 text-white border-2 border-blue-300'
                    : isCv
                      ? 'bg-blue-900/60 text-blue-200 border border-blue-500/60'
                      : 'bg-gray-700 text-gray-200 border border-gray-600 hover:bg-gray-600',
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
                <Sparkles
                  size={10}
                  className="absolute top-0.5 right-0.5 text-yellow-300"
                  aria-hidden
                />
              )}
            </button>
          )
        })}
      </div>
      {cvPrediction != null && (
        <div className="text-[10px] text-gray-500">
          {t('annotator.hit_zone_cv_label', { zone: cvPrediction })}
        </div>
      )}
    </div>
  )
}
