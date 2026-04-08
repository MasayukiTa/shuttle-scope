// 推奨アドバイスランキング（優先度スコア順）
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/hooks/useAuth'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { perfColor, BAR } from '@/styles/colors'

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
  // プレイヤー向けは伸びしろ言語に変換
  const displayTitle = isPlayer
    ? item.title.replace('改善余地', '伸びしろ').replace('要改善', '成長エリア')
    : item.title
  const displayBody = isPlayer
    ? item.body.replace('勝率', '活躍率').replace('弱点', '伸びしろ')
    : item.body

  return (
    <div className="flex gap-3 items-start bg-gray-750 rounded-lg p-3 border border-gray-700">
      {/* ランクバッジ */}
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
        style={{ backgroundColor: BAR, opacity: 1 - item.rank * 0.1 + 0.3 }}
      >
        {item.rank}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium text-gray-200 leading-tight">{displayTitle}</p>
          <span className="text-xs text-gray-400 shrink-0">{item.confidence_level}</span>
        </div>
        <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{displayBody}</p>

        {/* 優先度バー */}
        <div className="mt-2 flex items-center gap-2">
          <div className="flex-1 bg-gray-700 rounded h-1.5">
            <div
              className="h-full rounded"
              style={{
                width: `${Math.round(item.priority_score * 100)}%`,
                backgroundColor: perfColor(item.win_rate),
              }}
            />
          </div>
          <span className="text-xs text-gray-500 font-mono">{Math.round(item.priority_score * 100)}pt</span>
        </div>
      </div>
    </div>
  )
}

export function RecommendationRanking({ playerId }: RecommendationRankingProps) {
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
        <h3 className="text-sm font-semibold text-gray-200 mb-3">推奨アドバイス</h3>
        <div className="text-gray-500 text-sm py-4 text-center">読み込み中...</div>
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
