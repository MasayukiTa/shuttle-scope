/**
 * AdviceStrip — 「速報アドバイス」を任意の画面に挿入できる軽量 strip。
 *
 * 信頼性原則:
 *   - サーバ側 (/api/advice) が必ず実データから計算した文字列のみを返す。
 *   - フロントは文章を組み立てない。受け取った text をそのまま表示するだけ。
 *   - データ不足時 (advice=null) は「計測中」を素直に表示。「それっぽい」テキストを
 *     代用しない (信頼性最優先)。
 *
 * 各 advice には basis (source / sample_size / period) が付くので、
 *   ユーザは「ⓘ 根拠」リンクから根拠を辿れる。
 */
import { useEffect, useState } from 'react'
import { apiGet } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { trackAnalysisInteraction } from '@/utils/analytics'

export type AdviceContext =
  | 'dashboard.overview'
  | 'post_match_save'
  | 'condition.header'
  | 'prediction.tab'
  | 'growth.timeline'
  | 'player.home'

interface AdviceCard {
  text: string
  basis: Record<string, unknown>
  confidence: 'high' | 'medium' | 'low'
  severity: 'info' | 'positive' | 'warning'
  cta?: { label: string; action: string }
}

interface AdviceResponse {
  success: boolean
  advice: AdviceCard | null
  status: 'ok' | 'insufficient_data'
  reason?: string
  period?: string
}

interface Props {
  context: AdviceContext
  playerId?: number
  matchId?: number
  opponentId?: number
  /** insufficient 時に strip 自体を hide するなら true。default は false (透明な「計測中」を出す) */
  hideWhenInsufficient?: boolean
  className?: string
}

const SEVERITY_CLASS: Record<string, string> = {
  info:     'border-blue-300 dark:border-blue-700/60 bg-blue-50 dark:bg-blue-900/20 text-blue-900 dark:text-blue-100',
  positive: 'border-emerald-300 dark:border-emerald-700/60 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-900 dark:text-emerald-100',
  warning:  'border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-900/20 text-amber-900 dark:text-amber-100',
}

const CONFIDENCE_LABEL: Record<string, string> = {
  high: '信頼度: 高',
  medium: '信頼度: 中',
  low: '信頼度: 低',
}

export function AdviceStrip({
  context, playerId, matchId, opponentId, hideWhenInsufficient, className,
}: Props) {
  const [resp, setResp] = useState<AdviceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [showBasis, setShowBasis] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const params = new URLSearchParams({ context })
    if (playerId) params.set('player_id', String(playerId))
    if (matchId) params.set('match_id', String(matchId))
    if (opponentId) params.set('opponent_id', String(opponentId))
    apiGet<AdviceResponse>(`/advice?${params.toString()}`)
      .then((r) => { if (!cancelled) setResp(r) })
      .catch(() => { if (!cancelled) setResp(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [context, playerId, matchId, opponentId])

  if (loading) {
    return (
      <div className={`rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-3 py-2 ${className || ''}`}>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
          アドバイスを計算しています…
        </div>
      </div>
    )
  }

  // データ不足 → 「計測中」を素直に出す (それっぽい代替テキストは絶対に出さない)
  if (!resp || resp.status === 'insufficient_data' || !resp.advice) {
    if (hideWhenInsufficient) return null
    return (
      <div className={`rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60 px-3 py-2 ${className || ''}`}>
        <div className="flex items-start gap-2">
          <MIcon name="analytics" size={14} className="text-gray-400 mt-0.5 shrink-0" />
          <div className="text-xs text-gray-600 dark:text-gray-300">
            <div className="font-medium">アドバイスは計測中です</div>
            <div className="mt-0.5 text-gray-500 dark:text-gray-400">
              {resp?.reason || 'データが揃い次第、具体的な観測を表示します。それまで推測ベースのコメントは出しません (信頼性最優先)。'}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const a = resp.advice
  const cls = SEVERITY_CLASS[a.severity] || SEVERITY_CLASS.info
  return (
    <div className={`rounded-md border px-3 py-2 ${cls} ${className || ''}`}>
      <div className="flex items-start gap-2">
        <MIcon name="lightbulb" size={14} className="mt-0.5 shrink-0 opacity-80" />
        <div className="flex-1 min-w-0">
          <div className="text-sm leading-snug">{a.text}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] opacity-75">
            <span>{CONFIDENCE_LABEL[a.confidence] || a.confidence}</span>
            <button
              type="button"
              onClick={() => {
                setShowBasis((v) => !v)
                trackAnalysisInteraction(`advice.${context}`, 'toggle_basis', a.confidence)
              }}
              className="underline hover:no-underline"
            >
              {showBasis ? '根拠を隠す' : 'ⓘ 根拠'}
            </button>
            {a.cta && (
              <span className="ml-1 inline-flex items-center gap-1">
                <MIcon name="arrow_right_alt" size={11} />
                <span>{a.cta.label}</span>
              </span>
            )}
          </div>
          {showBasis && (
            <pre className="mt-1 text-[10px] whitespace-pre-wrap break-all opacity-80">
              {JSON.stringify(a.basis, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
