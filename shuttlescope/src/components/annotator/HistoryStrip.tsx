/**
 * U4: AnnotatorPage 下段に置くストローク履歴ストリップ。
 *
 * 直近 N 件 (デフォルト 5) を横並び表示。クリックで動画 seek。
 * 折り畳みボタンで非表示にもできる (画面小さい時)。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'
import { getStyleForShot } from '@/constants/shotTypeColors'
import type { StrokeInput, ShotType } from '@/types'

interface HistoryStripProps {
  strokes: StrokeInput[]
  onSeek?: (timestampSec: number) => void
  maxItems?: number
}

export function HistoryStrip({ strokes, onSeek, maxItems = 5 }: HistoryStripProps) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState(false)
  const recent = strokes.slice(-maxItems)

  return (
    <div className="border-t border-gray-700 bg-gray-900/80 shrink-0">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-1 text-[10px] text-gray-500 hover:text-gray-300"
        aria-expanded={!collapsed}
      >
        <span className="uppercase tracking-wider">{t('annotator.ux.history_title', { n: strokes.length })}</span>
        <MIcon name={collapsed ? 'expand_less' : 'expand_more'} size={14} />
      </button>
      {!collapsed && (
        <div className="px-3 pb-2 overflow-x-auto">
          {recent.length === 0 ? (
            <div className="text-xs text-gray-600 py-1.5">{t('annotator.ux.history_empty')}</div>
          ) : (
            <ol className="flex items-center gap-2 min-w-min">
              {recent.map((s) => {
                const style = getStyleForShot(s.shot_type as ShotType)
                return (
                  <li key={s.stroke_num}>
                    <button
                      type="button"
                      onClick={() => s.timestamp_sec != null && onSeek?.(s.timestamp_sec)}
                      disabled={s.timestamp_sec == null}
                      title={`#${s.stroke_num} ${s.shot_type} (${(s.timestamp_sec ?? 0).toFixed(2)}s)`}
                      className={clsx(
                        'flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium border',
                        style.bg, style.text, style.border,
                        s.timestamp_sec != null ? 'hover:brightness-110' : 'opacity-60 cursor-default',
                      )}
                    >
                      <span className="font-mono opacity-80">#{s.stroke_num}</span>
                      <span aria-hidden>{style.icon}</span>
                      <span className="truncate max-w-[80px]">{s.shot_type}</span>
                    </button>
                  </li>
                )
              })}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}
