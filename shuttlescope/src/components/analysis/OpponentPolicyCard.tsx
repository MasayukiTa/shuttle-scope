import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { useResearchBundleSlice } from '@/contexts/ResearchBundleContext'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { useCardTheme } from '@/hooks/useCardTheme'
import { AnalysisFilters } from '@/types'
import { RefreshCw, WifiOff, ServerCrash, HelpCircle } from 'lucide-react'

interface PolicyEntry {
  dominant_shot: string
  dominant_freq: number
  entropy: number
  predictability: string
  shot_distribution: Record<string, number>
  n: number
}

interface ContextPolicy {
  context_key: string
  context: {
    score_phase: string
    rally_bucket: string
    zone: string | null
  }
  policy: PolicyEntry | undefined
}

interface OpponentPolicyData {
  global_policy: PolicyEntry
  context_policies: ContextPolicy[]
  total_strokes: number
}

interface Meta {
  tier: string
  evidence_level: string
  sample_size: number
  caution: string | null
}

interface Props {
  playerId: number
  filters: AnalysisFilters
}

// ─── エラー分類 ──────────────────────────────────────────────────────────────

type ErrorKind = 'network' | 'server' | 'unknown'

function classifyError(err: unknown): ErrorKind {
  if (!err) return 'unknown'
  const status = (err as any)?.status
  if (status != null) return status >= 500 ? 'server' : 'unknown'
  const msg: string = (err as any)?.message ?? ''
  if (msg.toLowerCase().includes('fetch') || err instanceof TypeError) return 'network'
  return 'unknown'
}

const ERROR_META: Record<ErrorKind, { icon: React.ReactNode; title: string; hint: string }> = {
  network: {
    icon: <WifiOff size={14} />,
    title: 'ネットワーク接続に失敗しました',
    hint: 'バックエンドが起動しているか確認してください。',
  },
  server: {
    icon: <ServerCrash size={14} />,
    title: 'サーバーエラーが発生しました',
    hint: '一時的な問題の可能性があります。再取得してください。',
  },
  unknown: {
    icon: <HelpCircle size={14} />,
    title: 'データ取得に失敗しました',
    hint: '再取得ボタンで再試行できます。',
  },
}

// ─── ユーティリティ ──────────────────────────────────────────────────────────

const SCORE_PHASE_LABELS: Record<string, string> = {
  early: '序盤', mid: '中盤', deuce: 'デュース', endgame: '終盤',
}
const RALLY_BUCKET_LABELS: Record<string, string> = {
  short: '短', medium: '中', long: '長',
}
const PREDICTABILITY_LABELS: Record<string, string> = {
  predictable: '予測可能',
  mixed: '混合',
  unpredictable: '予測困難',
}
// 予測性の簡易説明（tooltip / aria-label 用）
const PREDICTABILITY_HINTS: Record<string, string> = {
  predictable: '特定ショットへの集中度が高い（エントロピー低）',
  mixed: 'ショット選択にやや傾向がある',
  unpredictable: 'ショット選択が多様で読みにくい（エントロピー高）',
}

function getPredictabilityColor(key: string, isLight: boolean): string {
  const map: Record<string, [string, string]> = {
    predictable: ['text-amber-600', 'text-amber-400'],
    mixed: ['text-gray-500', 'text-gray-400'],
    unpredictable: ['text-sky-600', 'text-sky-400'],
  }
  const pair = map[key]
  if (!pair) return isLight ? 'text-gray-500' : 'text-gray-400'
  return isLight ? pair[0] : pair[1]
}

function pct(v: number | undefined) {
  return v != null ? `${(v * 100).toFixed(1)}%` : '—'
}

/** 最終取得時刻を "X分前" 形式でフォーマット */
function formatUpdatedAt(ts: number): string {
  if (!ts) return ''
  const diffMin = Math.floor((Date.now() - ts) / 60000)
  if (diffMin < 1) return 'たった今'
  if (diffMin < 60) return `${diffMin}分前`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `${diffH}時間前`
  return new Date(ts).toLocaleDateString('ja-JP', { month: 'short', day: 'numeric' })
}

// ─── EntropyBar ──────────────────────────────────────────────────────────────

function EntropyBar({ entropy, maxEntropy = 2.5, isLight }: { entropy: number | undefined; maxEntropy?: number; isLight: boolean }) {
  const safeEntropy = entropy ?? 0
  const ratio = Math.min(safeEntropy / maxEntropy, 1)
  return (
    <div className="flex items-center gap-1" data-testid="entropy-bar">
      <div className={`w-16 h-1.5 rounded-full overflow-hidden ${isLight ? 'bg-gray-200' : 'bg-gray-700'}`}>
        <div
          className="h-full rounded-full bg-sky-600"
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      <span className={`text-[10px] ${isLight ? 'text-gray-500' : 'text-gray-500'}`}>{safeEntropy.toFixed(2)}</span>
    </div>
  )
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────

export function OpponentPolicyCard({ playerId, filters }: Props) {
  const { card, cardInner, cardInnerAlt, textHeading, textSecondary, textMuted, textFaint, loading, isLight } = useCardTheme()
  const filterApiParams = {
    ...(filters.result !== 'all' ? { result: filters.result } : {}),
    ...(filters.tournamentLevel ? { tournament_level: filters.tournamentLevel } : {}),
    ...(filters.dateFrom ? { date_from: filters.dateFrom } : {}),
    ...(filters.dateTo ? { date_to: filters.dateTo } : {}),
  }

  type Resp = { success: boolean; data: OpponentPolicyData; meta: Meta }
  const { slice: bundled, loading: bundleLoading, provided } = useResearchBundleSlice<Resp>('opponent_policy')
  const indivQuery = useQuery({
    queryKey: ['opponent-policy', playerId, filters],
    queryFn: () =>
      apiGet<Resp>(
        '/analysis/opponent_policy',
        { player_id: playerId, ...filterApiParams }
      ),
    enabled: !!playerId && !provided && !bundleLoading,
  })
  const { isError, error, refetch, isFetching, dataUpdatedAt } = indivQuery
  const data = bundled ?? indivQuery.data
  const isLoading = provided ? bundleLoading : indivQuery.isLoading

  const meta = data?.meta
  const policyData = data?.data
  const global = policyData?.global_policy
  const contexts = (policyData?.context_policies ?? []).filter(ctx => ctx.policy != null).slice(0, 8)
  const errorKind = isError ? classifyError(error) : null

  return (
    <div className={`${card} rounded-lg p-4 space-y-3`} data-testid="opponent-policy-card">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <h3 className={`text-sm font-semibold ${textHeading}`}>対戦相手ポリシー分析</h3>
        <div className="flex items-center gap-2">
          <EvidenceBadge
            tier="research"
            evidenceLevel="exploratory"
            sampleSize={meta?.sample_size}
            recommendationAllowed={false}
          />
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            title="再取得"
            data-testid="refetch-button"
            className={`p-1 rounded transition-colors disabled:opacity-40 ${isLight ? 'hover:bg-gray-100 text-gray-500' : 'hover:bg-gray-700 text-gray-500'}`}
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* 最終取得時刻 */}
      {dataUpdatedAt > 0 && !isError && (
        <p className={`text-[10px] ${textFaint}`} data-testid="last-fetched">
          最終取得: {formatUpdatedAt(dataUpdatedAt)}
        </p>
      )}

      {/* エラー状態（分類別） */}
      {isError && errorKind && (
        <div
          className={`flex items-start gap-2 rounded-md px-3 py-2 text-xs ${
            isLight ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-red-900/20 text-red-400 border border-red-800/40'
          }`}
          data-testid={`error-state-${errorKind}`}
        >
          <span className="mt-0.5 shrink-0">{ERROR_META[errorKind].icon}</span>
          <div className="space-y-0.5">
            <p className="font-medium">{ERROR_META[errorKind].title}</p>
            <p className={isLight ? 'text-red-600' : 'text-red-500'}>{ERROR_META[errorKind].hint}</p>
          </div>
        </div>
      )}

      <ResearchNotice
        caution={meta?.caution ?? '対戦相手ポリシーはショット分布の記述統計です。戦術的意図の推定は含みません。'}
        assumptions="ショット種別はアノテーションに依存。コンテキストはスコアフェーズ・ラリー長・ゾーンで定義。"
        promotionCriteria="コンテキストごとN≥30ストローク・複数対戦での再現性確認"
      />

      {isLoading ? (
        <p className={`text-sm text-center py-4 ${loading}`} data-testid="loading-state">計算中...</p>
      ) : !global ? (
        /* 空データ状態: エラーではなくデータ不足 */
        <div className={`text-center py-6 space-y-1`} data-testid="empty-state">
          <p className={`text-sm ${textMuted}`}>対戦ストロークデータが不足しています</p>
          <p className={`text-[10px] ${textFaint}`}>
            アノテーションが増えるとポリシー分析が表示されます
            {meta?.sample_size != null && meta.sample_size > 0 && (
              <span>（現在 N={meta.sample_size}）</span>
            )}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* 全体ポリシー */}
          <div className={`${cardInner} rounded px-3 py-2 space-y-1.5`}>
            <div className="flex items-center justify-between">
              <span className={`text-[11px] ${textSecondary}`}>全体ポリシー</span>
              <span className={`text-[10px] ${textFaint}`}>
                N={policyData?.total_strokes ?? 0} ストローク（フィルター適用後）
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <div>
                <span className={`text-xs ${textMuted}`}>主要ショット: </span>
                <span className={`text-xs font-medium ${textHeading}`}>{global.dominant_shot}</span>
                <span className={`text-[10px] ml-1 ${textFaint}`}>({pct(global.dominant_freq)})</span>
              </div>
              <div
                className="flex items-center gap-1"
                title={PREDICTABILITY_HINTS[global.predictability] ?? ''}
              >
                <span className={`text-xs ${textMuted}`}>予測性:</span>
                <span className={`text-xs font-medium ${getPredictabilityColor(global.predictability, isLight)}`}>
                  {PREDICTABILITY_LABELS[global.predictability] ?? global.predictability}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <span className={`text-[10px] ${textMuted}`}>エントロピー:</span>
              <EntropyBar entropy={global.entropy} isLight={isLight} />
            </div>
          </div>

          {/* コンテキスト別 */}
          {contexts.length > 0 && (
            <div className="space-y-1">
              <p className={`text-[10px] ${textMuted}`}>コンテキスト別ポリシー（上位{contexts.length}件）</p>
              {contexts.map((ctx, i) => {
                const policy = ctx.policy!
                return (
                  <div key={i} className={`${cardInnerAlt} rounded px-2 py-1.5 flex items-center justify-between`}>
                    <div className="space-y-0.5">
                      <div className={`text-[10px] ${textSecondary}`}>
                        {SCORE_PHASE_LABELS[ctx.context.score_phase] ?? ctx.context.score_phase}
                        / {RALLY_BUCKET_LABELS[ctx.context.rally_bucket] ?? ctx.context.rally_bucket}ラリー
                        {ctx.context.zone && ` / ${ctx.context.zone}`}
                      </div>
                      <div className="text-[10px]">
                        <span className={`font-medium ${textHeading}`}>{policy.dominant_shot}</span>
                        <span className={`ml-1 ${textFaint}`}>({pct(policy.dominant_freq)})</span>
                        <span
                          className={`ml-2 ${getPredictabilityColor(policy.predictability, isLight)}`}
                          title={PREDICTABILITY_HINTS[policy.predictability] ?? ''}
                        >
                          {PREDICTABILITY_LABELS[policy.predictability] ?? policy.predictability}
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <EntropyBar entropy={policy.entropy} isLight={isLight} />
                      <span className={`text-[10px] ${textFaint}`}>N={policy.n}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* 解釈補足 */}
          <div className={`space-y-0.5 text-[10px] ${textFaint}`}>
            <p>エントロピー高 = ショット選択が多様（予測困難）。エントロピー低 = 特定ショットに集中（予測可能）。</p>
            <p>予測可能 ▶ 返球パターンを絞りやすい。予測困難 ▶ 配球の多様性に注意。</p>
          </div>

          {/* 横連携ヒント */}
          <p className={`text-[10px] ${textFaint} border-t pt-2 ${isLight ? 'border-gray-200' : 'border-gray-700'}`}>
            詳細分析: OpponentStats・ShotWinLoss・PredictionPanel も併せて確認してください。
          </p>
        </div>
      )}
    </div>
  )
}
