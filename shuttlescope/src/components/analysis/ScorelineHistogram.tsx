// 実測スコアライン頻度ヒストグラム — Phase D キャリブレーション
import { useTranslation } from 'react-i18next'
import { WIN, LOSS } from '@/styles/colors'

interface ScorelineEntry {
  outcome: string
  scoreline: string
  count: number
  frequency: number
}

interface ScorelineHistogramProps {
  data: ScorelineEntry[]
}

export function ScorelineHistogram({ data }: ScorelineHistogramProps) {
  const { t } = useTranslation()

  if (!data || data.length === 0) {
    return null
  }

  const maxFreq = Math.max(...data.map((d) => d.frequency))

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-gray-400 mb-2">
        {t('prediction.scoreline_histogram')}
      </p>
      {data.map((entry, i) => {
        const isWin = entry.outcome.startsWith('2') || Number(entry.outcome[0]) > Number(entry.outcome[2])
        const pct = Math.round(entry.frequency * 100)
        const barWidth = maxFreq > 0 ? Math.round((entry.frequency / maxFreq) * 100) : 0
        return (
          <div key={i} className="flex items-center gap-2 text-xs py-0.5">
            {/* 結果バッジ（固定幅） */}
            <span
              className="font-bold w-8 shrink-0 text-right"
              style={{ color: isWin ? WIN : LOSS }}
            >
              {entry.outcome}
            </span>
            {/* バー（スコアラベルなし） */}
            <div className="flex-1 bg-gray-700 rounded h-4 relative overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${barWidth}%`,
                  backgroundColor: isWin ? WIN : LOSS,
                  opacity: 0.7,
                }}
              />
            </div>
            {/* %と回数 */}
            <span className="text-gray-500 w-8 text-right font-mono shrink-0">{pct}%</span>
            <span className="text-gray-600 w-6 text-right shrink-0">{entry.count}</span>
            {/* セットスコア: details で折り畳み */}
            <details className="shrink-0">
              <summary className="text-blue-500 cursor-pointer list-none text-[10px] leading-none">詳細</summary>
              <div className="text-gray-500 text-[10px] mt-0.5 whitespace-nowrap">{entry.scoreline}</div>
            </details>
          </div>
        )
      })}
      <p className="text-[10px] text-gray-600 mt-1">
        {t('prediction.frequency')} — 実測スコアライン（統計ベース）
      </p>
    </div>
  )
}
