// EPVカードコンポーネント（マルコフ連鎖に基づく期待パターン価値）
// 上位パターン: 全ロール表示 / 下位パターン: アナリスト・コーチのみ
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'

interface MarkovEPVProps {
  playerId: number
}

interface EPVPattern {
  pattern: string
  shots: string[]
  epv: number
  ci_low: number
  ci_high: number
  count: number
}

interface EPVResponse {
  success: boolean
  data: {
    top_patterns: EPVPattern[]
    bottom_patterns: EPVPattern[]
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function EPVCard({ pattern, isPositive }: { pattern: EPVPattern; isPositive: boolean }) {
  const bgColor = isPositive ? 'bg-blue-900/30 border-blue-700' : 'bg-amber-900/30 border-amber-700'
  const epvColor = isPositive ? 'text-blue-300' : 'text-amber-300'
  const epvSign = pattern.epv >= 0 ? '+' : ''

  return (
    <div className={`rounded-lg p-3 border ${bgColor}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-white font-medium truncate">{pattern.pattern}</p>
          <p className="text-xs text-gray-400 mt-0.5">出現数: {pattern.count}</p>
        </div>
        <div className="text-right shrink-0">
          <p className={`text-lg font-bold ${epvColor}`}>
            {epvSign}{(pattern.epv * 100).toFixed(1)}
          </p>
          <p className="text-[10px] text-gray-500">
            [{(pattern.ci_low * 100).toFixed(1)}, {(pattern.ci_high * 100).toFixed(1)}]
          </p>
        </div>
      </div>
    </div>
  )
}

export function MarkovEPV({ playerId }: MarkovEPVProps) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-epv', playerId],
    queryFn: () =>
      apiGet<EPVResponse>('/analysis/epv', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.loading')}</div>
  }

  const sampleSize = resp?.meta?.sample_size ?? 0
  const topPatterns = resp?.data?.top_patterns ?? []
  const bottomPatterns = resp?.data?.bottom_patterns ?? []

  if (sampleSize === 0 && topPatterns.length === 0) {
    return <div className="text-gray-500 text-sm py-4 text-center">{t('analysis.no_data')}</div>
  }

  return (
    <div className="space-y-4">
      <ConfidenceBadge sampleSize={sampleSize} />

      {/* 上位パターン（全ロール） */}
      <div>
        <h3 className="text-sm font-semibold text-blue-400 mb-2">{t('analysis.epv.top_patterns')}</h3>
        {topPatterns.length === 0 ? (
          <p className="text-gray-500 text-xs">{t('analysis.no_data')}</p>
        ) : (
          <div className="space-y-2">
            {topPatterns.slice(0, 5).map((p, i) => (
              <EPVCard key={i} pattern={p} isPositive={true} />
            ))}
          </div>
        )}
      </div>

      {/* 下位パターン（アナリスト・コーチのみ） */}
      <RoleGuard
        allowedRoles={['analyst', 'coach']}
        fallback={null}
      >
        <div>
          <h3 className="text-sm font-semibold text-amber-400 mb-2">{t('analysis.epv.bottom_patterns')}</h3>
          {bottomPatterns.length === 0 ? (
            <p className="text-gray-500 text-xs">{t('analysis.no_data')}</p>
          ) : (
            <div className="space-y-2">
              {bottomPatterns.slice(0, 5).map((p, i) => (
                <EPVCard key={i} pattern={p} isPositive={false} />
              ))}
            </div>
          )}
        </div>
      </RoleGuard>

      <p className="text-[10px] text-gray-600">
        EPV値: ベースライン勝率からの差分（正 = プラス効果）
      </p>
    </div>
  )
}
