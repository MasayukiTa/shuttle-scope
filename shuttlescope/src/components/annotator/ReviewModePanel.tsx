/**
 * U3 確認モード — CV候補・ラリー境界候補・identity マッピングなどを表示する。
 *
 * 統合口 (addendum §3): いずれもデータが無い場合は黙って空表示。
 *  - CVAssistPanel: 既存ロジックを差し込む (現状は placeholder hint)
 *  - RallyBoundary 候補: Track A5 出力データ (まだバッチ未統合のため空)
 *  - IdentityGraph mapping: Track A3 出力 (router 内部に statefull、UI 連携前)
 *  - SwingDetector confidence: Track C3 出力 (バッチ未統合)
 *
 * 現段階では確認モード切替時に「ここに確認用の情報が入る」案内を表示しつつ、
 * 既存 CVAssistPanel コンポーネントを下に表示する placeholder。
 * 完全統合 (cv_candidates fetch 済データの差し込み) は AnnotatorPage 側で
 * その props を渡す形で実装する。
 */
import { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface ReviewModePanelProps {
  /** 既存の CVAssistPanel JSX をそのまま inject するためのスロット */
  cvAssist?: ReactNode
  rallyBoundaryCount?: number
  identityMappingCount?: number
  swingEventCount?: number
}

export function ReviewModePanel({
  cvAssist,
  rallyBoundaryCount = 0,
  identityMappingCount = 0,
  swingEventCount = 0,
}: ReviewModePanelProps) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="flex items-center justify-between px-3 py-2 border-b border-gray-700 shrink-0 bg-gray-800/40">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-200">
          <MIcon name="visibility" size={18} />
          {t('annotator.ux.review_header')}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-gray-500">
          <span>{t('annotator.ux.review_count_boundary', { n: rallyBoundaryCount })}</span>
          <span>{t('annotator.ux.review_count_identity', { n: identityMappingCount })}</span>
          <span>{t('annotator.ux.review_count_swing', { n: swingEventCount })}</span>
        </div>
      </header>
      <div className="flex-1 px-3 py-2 space-y-3">
        {cvAssist ?? (
          <div className="text-xs text-gray-500 leading-relaxed">
            {t('annotator.ux.review_empty')}
          </div>
        )}
      </div>
    </div>
  )
}
