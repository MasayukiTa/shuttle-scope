// 推奨アドバイスランキング（優先度スコア順）
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/hooks/useAuth'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { perfColor, N_GRAY, A_GOOD } from '@/styles/colors'
import { useTranslation } from 'react-i18next'

interface RecommendationRankingProps {
  playerId: number
}

interface RankItem {
  rank: number
  category: string
  key?: string
  title: string
  body: string
  priority_score: number
  sample_size: number
  confidence_level: string
  win_rate: number
  baseline?: number
  delta_from_baseline?: number
}

interface Response {
  success: boolean
  data: { items: RankItem[]; baseline?: number }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

function RankCard({ item, isPlayer }: { item: RankItem; isPlayer: boolean }) {
  const { t } = useTranslation()

  // プレイヤー向けは伸びしろ言語に変換
  const displayTitle = isPlayer
    ? item.title.replace('改善余地', '伸びしろ').replace('要改善', '成長エリア')
    : item.title
  const displayBody = isPlayer
    ? item.body.replace('勝率', '活躍率').replace('弱点', '伸びしろ')
    : item.body

  // Design Language v1.2 §12.4 色予算: rank 1 のみ色を出す、それ以外は無彩色。
  // Rank 1 は意思決定上「まずこれ」を意味する (= 決定支援としての色)。
  // 旧版: BAR (#8db0fe 薄青) + text-white (コントラスト ~1.8:1 WCAG 失格)
  // 新版: rank=1 は A_GOOD + 白文字 (§2.7 contrast OK)
  //        rank>=2 は N_GRAY[600] + 白文字 (こちらも contrast 充分)
  const isTop = item.rank === 1
  const badgeBg = isTop ? A_GOOD : N_GRAY[600]
  return (
    <div
      className="flex gap-3 items-start rounded p-3 border"
      style={{
        backgroundColor: N_GRAY[800],
        borderColor: isTop ? A_GOOD : N_GRAY[700],
        borderLeftWidth: isTop ? 3 : 1,
      }}
    >
      {/* ランクバッジ */}
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
        style={{ backgroundColor: badgeBg, color: '#ffffff' }}
      >
        {item.rank}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium leading-tight" style={{ color: N_GRAY[100] }}>
            {displayTitle}
          </p>
          <span className="text-xs shrink-0" style={{ color: N_GRAY[400] }}>
            {item.confidence_level}
          </span>
        </div>
        <p className="text-xs mt-0.5 leading-relaxed" style={{ color: N_GRAY[300] }}>
          {displayBody}
        </p>

        {/* 優先度バー: 長さで読む。色は perfColor (coolwarm 連続) のみ許可 */}
        <div className="mt-2 flex items-center gap-2">
          <div
            className="flex-1 rounded h-1.5"
            style={{ backgroundColor: N_GRAY[700] }}
          >
            <div
              className="h-full rounded"
              style={{
                width: `${Math.round(item.priority_score * 100)}%`,
                backgroundColor: perfColor(item.win_rate),
              }}
            />
          </div>
          <span
            className="text-xs font-mono tabular-nums"
            style={{ color: N_GRAY[500] }}
          >
            {Math.round(item.priority_score * 100)}pt
          </span>
        </div>
      </div>
    </div>
  )
}

export function RecommendationRanking({ playerId }: RecommendationRankingProps) {
  const { t } = useTranslation()

  const { role } = useAuth()
  const isPlayer = role === 'player'

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-recommendation-ranking', playerId],
    queryFn: () => apiGet<Response>('/analysis/recommendation_ranking', { player_id: playerId }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">{t('auto.RecommendationRanking.k1')}</h3>
        <div className="text-gray-500 text-sm py-4 text-center">{t('auto.RecommendationRanking.k2')}</div>
      </div>
    )
  }

  const items = resp?.data?.items ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-200 mb-3">
        {isPlayer ? '今週の成長ポイント' : '推奨アドバイスランキング'}
      </h3>

      {items.length === 0 ? (
        <NoDataMessage sampleSize={sampleSize} minRequired={5} unit="ラリー" />
      ) : (
        <div className="space-y-2">
          <ConfidenceBadge sampleSize={sampleSize} />
          <div className="space-y-2 mt-2">
            {items.map(item => (
              <RankCard key={item.rank} item={item} isPlayer={isPlayer} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
