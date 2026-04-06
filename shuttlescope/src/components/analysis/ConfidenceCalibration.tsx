// 信頼度キャリブレーション — データ品質分布の表示（概要タブ下部）
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { seqBlue } from '@/styles/colors'

interface ConfidenceCalibrationProps {
  playerId: number
}

interface TierEntry {
  tier: string
  label_en: string
  count: number
  ratio: number
}

interface Response {
  success: boolean
  data: {
    distribution: TierEntry[]
    total_metrics: number
    overall_quality: string
    min_matches_for_high: number
    current_match_count: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const TIER_COLORS: Record<string, string> = {
  insufficient: 'bg-red-900/40 border-red-700 text-red-300',
  low:          'bg-yellow-900/40 border-yellow-700 text-yellow-300',
  medium:       'bg-blue-900/30 border-blue-700 text-blue-300',
  high:         'bg-blue-700/50 border-blue-500 text-blue-200',
}

export function ConfidenceCalibration({ playerId }: ConfidenceCalibrationProps) {
  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-confidence-calibration', playerId],
    queryFn: () => apiGet<Response>('/analysis/confidence_calibration', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-2">データ品質概況</h3>
        <div className="text-gray-500 text-sm py-2 text-center">読み込み中...</div>
      </div>
    )
  }

  const d = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0
  const dist = d?.distribution ?? []

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-200">データ品質概況</h3>
        {d && (
          <span className="text-xs text-gray-400">
            全体品質: <span className="text-gray-200 font-semibold">{d.overall_quality}</span>
          </span>
        )}
      </div>

      <ConfidenceBadge sampleSize={sampleSize} />

      {d && (
        <>
          {/* 品質バー */}
          <div className="mt-3 flex gap-0.5 h-4 rounded overflow-hidden">
            {dist.map(t => (
              t.ratio > 0 && (
                <div
                  key={t.label_en}
                  style={{ width: `${t.ratio * 100}%`, backgroundColor: seqBlue(
                    t.label_en === 'high' ? 1.0 :
                    t.label_en === 'medium' ? 0.65 :
                    t.label_en === 'low' ? 0.35 : 0.1
                  ) }}
                  title={`${t.tier}: ${t.count}指標`}
                />
              )
            ))}
          </div>

          {/* 内訳 */}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {dist.map(t => (
              <div
                key={t.label_en}
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs ${TIER_COLORS[t.label_en] ?? ''}`}
              >
                <span>{t.tier}</span>
                <span className="font-mono font-semibold">{t.count}</span>
              </div>
            ))}
          </div>

          {/* ガイダンステキスト */}
          {d.current_match_count < d.min_matches_for_high && (
            <p className="mt-2 text-xs text-gray-400">
              高信頼分析にはあと
              <span className="mx-1 font-semibold text-gray-200">
                {d.min_matches_for_high - d.current_match_count}試合
              </span>
              のデータが必要です（現在: {d.current_match_count}試合）
            </p>
          )}
        </>
      )}
    </div>
  )
}
