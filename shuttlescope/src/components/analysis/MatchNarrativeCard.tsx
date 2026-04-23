/**
 * MatchNarrativeCard — 試合前予測サマリー
 *
 * 勝敗判定・最有力スコア・決め手・ぐだりやすい局面・試合前の既知情報を
 * 1 枚のカードで表示する。PredictionPanel の冒頭に置く。
 */
import { Swords, Target, AlertTriangle, Info } from 'lucide-react'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'

export interface MatchNarrative {
  verdict: string          // "勝利有力" | "やや優勢" | "五分五分" | "やや不利" | "苦戦が予想"
  verdict_level: 'win' | 'neutral' | 'loss'
  likely_score: string     // "2-1 勝利（21-18 / 19-21 / 21-16）— 52%"
  deciding_factor: string  // 決め手の文章
  risk_zones: string[]     // ぐだりやすい局面
  knowns: string[]         // 試合前の既知情報
}

interface Props {
  narrative: MatchNarrative
  playerName: string
  opponentName?: string
}

export function MatchNarrativeCard({ narrative, playerName, opponentName }: Props) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()

  const verdictColor =
    narrative.verdict_level === 'win'
      ? WIN
      : narrative.verdict_level === 'loss'
      ? LOSS
      : isLight ? '#78716c' : '#9ca3af'

  const cardBg = isLight ? '#ffffff' : '#1e293b'
  const cardBorder = isLight ? '#e2e8f0' : '#334155'
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#1e293b' : '#f1f5f9'
  const sectionBg = isLight ? '#f8fafc' : '#0f172a'

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: cardBg, border: `1px solid ${cardBorder}` }}
    >
      {/* ── ヘッダー: 判定バナー ── */}
      <div
        className="px-4 py-3 flex items-center justify-between gap-3"
        style={{
          background: narrative.verdict_level === 'win'
            ? (isLight ? '#f0fdf4' : '#14532d33')
            : narrative.verdict_level === 'loss'
            ? (isLight ? '#fff1f2' : '#4c0519' + '33')
            : (isLight ? '#f8fafc' : '#1e293b'),
          borderBottom: `1px solid ${cardBorder}`,
        }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Swords size={15} style={{ color: verdictColor, flexShrink: 0 }} />
          <div className="min-w-0">
            <p className="text-xs font-medium" style={{ color: subText }}>
              試合前予測
              {opponentName && (
                <span className="ml-1">vs {opponentName}</span>
              )}
            </p>
            <p className="text-lg font-bold leading-tight" style={{ color: verdictColor }}>
              {playerName}：{narrative.verdict}
            </p>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[10px]" style={{ color: subText }}>{t('auto.MatchNarrativeCard.k1')}</p>
          <p className="text-xs font-mono font-semibold" style={{ color: neutral }}>
            {narrative.likely_score}
          </p>
        </div>
      </div>

      {/* ── ボディ ── */}
      <div className="divide-y" style={{ borderColor: cardBorder }}>

        {/* 決め手 */}
        <div className="px-4 py-3 flex gap-2.5">
          <Target size={13} style={{ color: verdictColor, flexShrink: 0, marginTop: 2 }} />
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide mb-0.5" style={{ color: subText }}>
              決め手
            </p>
            <p className="text-xs leading-relaxed" style={{ color: neutral }}>
              {narrative.deciding_factor}
            </p>
          </div>
        </div>

        {/* ぐだりやすい局面 */}
        <div className="px-4 py-3 flex gap-2.5">
          <AlertTriangle size={13} style={{ color: '#d97706', flexShrink: 0, marginTop: 2 }} />
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: subText }}>
              ぐだりやすい局面
            </p>
            <ul className="space-y-0.5">
              {narrative.risk_zones.map((z, i) => (
                <li key={i} className="text-xs" style={{ color: neutral }}>
                  • {z}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 試合前の既知情報 */}
        <div
          className="px-4 py-2.5 flex gap-2.5"
          style={{ background: sectionBg }}
        >
          <Info size={12} style={{ color: subText, flexShrink: 0, marginTop: 2 }} />
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: subText }}>
              試合前に分かっていること
            </p>
            <div className="flex flex-wrap gap-1.5">
              {narrative.knowns.map((k, i) => (
                <span
                  key={i}
                  className="text-[10px] px-1.5 py-0.5 rounded"
                  style={{
                    background: isLight ? '#e2e8f0' : '#334155',
                    color: isLight ? '#475569' : '#94a3b8',
                  }}
                >
                  {k}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
