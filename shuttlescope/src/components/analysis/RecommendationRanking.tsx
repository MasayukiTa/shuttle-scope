// 推奨アドバイスランキング（優先度スコア順）
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/hooks/useAuth'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { hasSufficientSample } from '@/utils/sampleGate'

/** これ未満のストローク数ではランキングを出さない (監査 #438)。 */
const RECOMMENDATION_MIN_STROKES = 5
import { perfColor, N_GRAY, A_GOOD } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'

interface RecommendationRankingProps {
  playerId: number
}

// 製品ルール (CLAUDE.md): player 向け画面に勝率ベースの判定・弱点表現を見せない。
// このランキングは win_rate / baseline から作った本文と優先度バーを持つため、
// 語の置換 (勝率→活躍率 等) では同じ指標の別名になるだけで規則を満たせない。
// player ロールでは取得も描画もしない (fail-closed)。

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

function RankCard({ item }: { item: RankItem }) {
  const isLight = useIsLightMode()
  const displayTitle = item.title
  const displayBody = item.body

  // Design Language v1.2 §12.4: rank 1 は title weight と badge 色で強調する。
  // **左罫線で色を立てるデザインは禁止** (詐欺サイト感が出るため)。
  // 色の役割:
  //   - ランクバッジ: rank 1 = A_GOOD、rank ≥ 2 = N_GRAY
  //   - タイトル: rank 1 のみ font-bold (色は中立)
  //   - 優先度バー: 長さ + coolwarm 色 (連続値の合法例外)
  const isTop = item.rank === 1
  const badgeBg = isTop ? A_GOOD : (isLight ? N_GRAY[400] : N_GRAY[600])
  const tokens = isLight
    ? {
        bg: '#ffffff',
        border: N_GRAY[200],
        textTitle: N_GRAY[900],
        textBody:  N_GRAY[700],
        textMuted: N_GRAY[500],
        barTrack:  N_GRAY[200],
      }
    : {
        bg: N_GRAY[800],
        border: N_GRAY[700],
        textTitle: N_GRAY[50],
        textBody:  N_GRAY[200],
        textMuted: N_GRAY[400],
        barTrack:  N_GRAY[700],
      }

  return (
    <div
      className="flex gap-3 items-start rounded-ss-md p-3 bg-[var(--ss-surface-2)] border border-[var(--ss-border)]"
    >
      {/* ランクバッジ: rank 1 だけ A_GOOD、それ以外は無彩色 */}
      <div
        className="w-7 h-7 rounded-ss-md flex items-center justify-center text-xs font-bold shrink-0 ss-num"
        style={{ backgroundColor: badgeBg, color: '#ffffff' }}
      >
        {item.rank}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p
            className={`text-sm leading-tight ${isTop ? 'font-bold' : 'font-medium'}`}
            style={{ color: tokens.textTitle }}
          >
            {displayTitle}
          </p>
          <span className="text-xs shrink-0" style={{ color: tokens.textMuted }}>
            {item.confidence_level}
          </span>
        </div>
        <p className="text-xs mt-0.5 leading-relaxed" style={{ color: tokens.textBody }}>
          {displayBody}
        </p>

        {/* 優先度バー: 長さで読む。色は perfColor (coolwarm 連続) のみ許可 */}
        <div className="mt-2 flex items-center gap-2">
          <div
            className="flex-1 rounded-ss-md h-1.5"
            style={{ backgroundColor: tokens.barTrack }}
          >
            <div
              className="h-full rounded-ss-md duration-base ease-out"
              style={{
                width: `${Math.round(item.priority_score * 100)}%`,
                backgroundColor: perfColor(item.win_rate),
              }}
            />
          </div>
          <span
            className="text-xs font-mono ss-num"
            style={{ color: tokens.textMuted }}
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
  const isLight = useIsLightMode()
  const { role } = useAuth()
  const isPlayer = role === 'player'

  const outerTokens = isLight
    ? { bg: '#ffffff', border: N_GRAY[200], title: N_GRAY[900], muted: N_GRAY[500] }
    : { bg: N_GRAY[800], border: N_GRAY[700], title: N_GRAY[50],  muted: N_GRAY[400] }

  const { data: resp, isLoading } = useQuery({
    queryKey: ['analysis-recommendation-ranking', playerId],
    queryFn: () => apiGet<Response>('/analysis/recommendation_ranking', { player_id: playerId }),
    enabled: !!playerId && !isPlayer,
  })

  if (isPlayer) return null

  if (isLoading) {
    return (
      <div
        className="rounded-ss-lg p-4 bg-[var(--ss-surface-1)] border border-[var(--ss-border)]"
      >
        <h3 className="text-sm font-semibold mb-3" style={{ color: outerTokens.title }}>
          {t('auto.RecommendationRanking.k1')}
        </h3>
        <div className="text-sm py-4 text-center" style={{ color: outerTokens.muted }}>
          {t('auto.RecommendationRanking.k2')}
        </div>
      </div>
    )
  }

  const items = resp?.data?.items ?? []
  const sampleSize = resp?.meta?.sample_size ?? 0

  return (
    <div
      className="rounded-ss-lg p-4 bg-[var(--ss-surface-1)] border border-[var(--ss-border)]"
    >
      <h3 className="text-sm font-semibold mb-3" style={{ color: outerTokens.title }}>
        推奨アドバイスランキング
      </h3>

      {items.length === 0 || !hasSufficientSample(sampleSize, RECOMMENDATION_MIN_STROKES) ? (
        <NoDataMessage sampleSize={sampleSize} minRequired={RECOMMENDATION_MIN_STROKES} unit="ストローク" />
      ) : (
        <div className="space-y-2">
          <ConfidenceBadge sampleSize={sampleSize} tier="research" unit="strokes" />
          <div className="space-y-2 mt-2">
            {items.map(item => (
              <RankCard key={item.rank} item={item} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
