// 信頼度キャリブレーション — データ品質分布の表示（概要タブ下部）
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { seqBlue } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

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

// Design Language v1.2 §2.7: 同色相 bg + text 禁止。
// 旧 'high' は bg-blue-700/50 + text-blue-200 で青背景に薄い青文字 (= ユーザ
// 報告の「高信頼が読めない」)。全 tier neutral bg + accent text に統一。
const TIER_COLORS: Record<string, string> = {
  insufficient: 'bg-gray-800 border-gray-700 text-red-300',
  low:          'bg-gray-800 border-gray-700 text-amber-400',
  medium:       'bg-gray-800 border-gray-700 text-blue-300',
  high:         'bg-gray-800 border-blue-500 text-blue-300',
}

export function ConfidenceCalibration({ playerId }: ConfidenceCalibrationProps) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-confidence-calibration', playerId],
    queryFn: () => apiGet<Response>('/analysis/confidence_calibration', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-ss-lg shadow-card p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-2">{t('auto.ConfidenceCalibration.k1')}</h3>
        <div className="text-gray-500 text-sm py-2 text-center">{t('auto.ConfidenceCalibration.k2')}</div>
      </div>
    )
  }

  const d = resp?.data
  const sampleSize = resp?.meta?.sample_size ?? 0
  const dist = d?.distribution ?? []

  return (
    <div className="bg-gray-800 rounded-ss-lg shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-200">{t('auto.ConfidenceCalibration.k1')}</h3>
        {d && (
          <span className="text-xs text-gray-400">
            {t('auto.ConfidenceCalibration.overall_quality')} <span className="text-gray-200 font-semibold">{d.overall_quality}</span>
          </span>
        )}
      </div>

      <ConfidenceBadge sampleSize={sampleSize} />

      {d && (
        <>
          {/* 品質バー */}
          <div className="mt-3 flex gap-0.5 h-4 rounded-ss-sm overflow-hidden">
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
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded-ss-sm border text-xs ${TIER_COLORS[t.label_en] ?? ''}`}
              >
                <span>{t.tier}</span>
                <span className="font-mono font-semibold ss-num">{t.count}</span>
              </div>
            ))}
          </div>

          {/* ガイダンステキスト */}
          {d.current_match_count < d.min_matches_for_high && (
            <p className="mt-2 text-xs text-gray-400">
              {t('auto.ConfidenceCalibration.need_more_pre')}
              <span className="mx-1 font-semibold text-gray-200 ss-num">
                {t('auto.ConfidenceCalibration.n_matches', { n: d.min_matches_for_high - d.current_match_count })}
              </span>
              {t('auto.ConfidenceCalibration.need_more_post', { m: d.current_match_count })}
            </p>
          )}
        </>
      )}
    </div>
  )
}
