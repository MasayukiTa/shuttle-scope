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
import { useTranslation } from 'react-i18next'
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

// Design Language v1.2 §12: bg は neutral 固定、severity は文字色で運ぶ。
// 旧版は bg-{color}-50 / bg-{color}-900/20 の同色相 bg+text でカード全体が
// 色塗りされていたが、Design Language §12.4 (1 画面の色付き要素を絞る) に
// 違反。今は bg を完全に neutral 化し、icon と border 強調だけで識別する。
const SEVERITY_CLASS: Record<string, string> = {
  info:     'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100',
  positive: 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100',
  warning:  'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100',
}
// severity 別 icon 色 (色は icon + 文字符号のみで運ぶ)
const SEVERITY_ICON_COLOR: Record<string, string> = {
  info:     'text-gray-400 dark:text-gray-500',
  positive: 'text-blue-600 dark:text-blue-300',   // A_GOOD
  warning:  'text-amber-600 dark:text-amber-400', // CAUTION
}

export function AdviceStrip({
  context, playerId, matchId, opponentId, hideWhenInsufficient, className,
}: Props) {
  const { t } = useTranslation()
  const CONFIDENCE_LABEL: Record<string, string> = {
    high: t('advice.confidence_high', 'Confidence: High'),
    medium: t('advice.confidence_medium', 'Confidence: Medium'),
    low: t('advice.confidence_low', 'Confidence: Low'),
  }
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
          {t('advice.calculating', 'Calculating advice…')}
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
            <div className="font-medium">{t('advice.measuring_title', 'Advice is being measured')}</div>
            <div className="mt-0.5 text-gray-500 dark:text-gray-400">
              {resp?.reason || t('advice.measuring_body', 'Concrete observations will appear once enough data is collected. We do not show guess-based comments before then (reliability first).')}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const a = resp.advice
  const cls = SEVERITY_CLASS[a.severity] || SEVERITY_CLASS.info
  const iconCls = SEVERITY_ICON_COLOR[a.severity] || SEVERITY_ICON_COLOR.info
  return (
    <div className={`rounded-md border px-3 py-2 ${cls} ${className || ''}`}>
      <div className="flex items-start gap-2">
        <MIcon name="lightbulb" size={14} className={`mt-0.5 shrink-0 ${iconCls}`} />
        <div className="flex-1 min-w-0">
          <div className="text-sm leading-snug">{a.text}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] opacity-80">
            <span>{CONFIDENCE_LABEL[a.confidence] || a.confidence}</span>
            <span aria-hidden="true" className="opacity-50">{t('auto.AdviceStrip.dot')}</span>
            <button
              type="button"
              onClick={() => {
                setShowBasis((v) => !v)
                trackAnalysisInteraction(`advice.${context}`, 'toggle_basis', a.confidence)
              }}
              className="underline hover:no-underline"
            >
              {showBasis ? t('advice.hide_basis', 'Hide basis') : t('advice.show_basis', 'ⓘ Basis')}
            </button>
            {a.cta && (
              <>
                <span aria-hidden="true" className="opacity-50">{t('auto.AdviceStrip.dot')}</span>
                <span className="inline-flex items-center gap-1">
                  <MIcon name="arrow_right_alt" size={11} />
                  <span>{a.cta.label}</span>
                </span>
              </>
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
