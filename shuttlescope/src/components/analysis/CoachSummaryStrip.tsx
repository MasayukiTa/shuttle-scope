// CoachSummaryStrip — 試合前コーチ向け圧縮サマリー (Spec §3.1 / §10)
//
// Design Language v1.1 グレースケール先行ビルド (2026-05-19 改訂)
//   1. 骨格は N_GRAY だけで完成させる
//   2. 「結果の評価 (勝率) と recentForm」だけに A_GOOD / B_BAD を許す
//   3. 「最大リスク」は B_BAD で警告意味付け (装飾ではない)
//   4. 「推奨アクション」「最頻結果」は無彩色 (中立情報)
//   5. E_EMPHASIS は不使用 (本コンポーネントは passive 表示で能動アクション要求はない)
//
// 詳細仕様: private_docs/ShuttleScope_DESIGN_LANGUAGE_v1.md
import { useTranslation } from 'react-i18next'
import {
  A_GOOD, B_BAD, N_GRAY,
} from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface TacticalNote {
  note: string
  estimated_impact: string
  basis: string
}

interface Tokens {
  bgCard: string
  bgInner: string
  border: string
  textStrong: string
  textPrimary: string
  textMuted: string
  textFaint: string
  divider: string
}

interface CoachSummaryStripProps {
  winProbability: number
  confidence: number
  confidenceStars: string
  setDistribution: { '2-0': number; '2-1': number; '1-2': number; '0-2': number }
  cautionFlags: string[]
  tacticalNotes: Array<TacticalNote | string>
  sampleSize: number
  recentForm?: {
    trend: 'improving' | 'declining' | 'stable'
    win_rate: number
    sample: number
  }
}

/**
 * 勝率の符号色。中立帯 (0.45〜0.55) は色を付けない (= 微妙な差で
 * ユーザを誤誘導しない)。
 */
function winColor(p: number, neutral: string): string {
  if (p >= 0.55) return A_GOOD
  if (p <= 0.45) return B_BAD
  return neutral
}

function topOutcome(dist: CoachSummaryStripProps['setDistribution']): string {
  return Object.entries(dist).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'
}

export function CoachSummaryStrip({
  winProbability,
  confidence,
  confidenceStars,
  setDistribution,
  cautionFlags,
  tacticalNotes,
  sampleSize,
  recentForm,
}: CoachSummaryStripProps) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()

  // ── トークン (ライト/ダーク共通の N_GRAY 階調) ─────────────────────
  const tokens = isLight
    ? {
        bgCard:      N_GRAY[50],   // パネル背景
        bgInner:     '#ffffff',     // 内部カード背景
        border:      N_GRAY[200],
        textStrong:  N_GRAY[900],
        textPrimary: N_GRAY[800],
        textMuted:   N_GRAY[500],
        textFaint:   N_GRAY[400],
        divider:     N_GRAY[200],
      }
    : {
        bgCard:      N_GRAY[900],
        bgInner:     N_GRAY[800],
        border:      N_GRAY[700],
        textStrong:  N_GRAY[50],
        textPrimary: N_GRAY[100],
        textMuted:   N_GRAY[400],
        textFaint:   N_GRAY[500],
        divider:     N_GRAY[700],
      }

  const winPct = Math.round(winProbability * 100)
  const confPct = Math.round(confidence * 100)
  const topResult = topOutcome(setDistribution)
  const topRisk = cautionFlags[0] ?? null
  const firstNote = tacticalNotes[0]
  const topAction = firstNote
    ? (typeof firstNote === 'string' ? firstNote : firstNote.note)
    : null

  const winColorVal = winColor(winProbability, tokens.textStrong)
  const lowSample = sampleSize < 10

  return (
    <section
      className="rounded-md border mb-4"
      style={{ backgroundColor: tokens.bgCard, borderColor: tokens.border }}
      aria-label={t('prediction.coach_summary') || 'コーチ向けサマリー'}
    >
      {/* ヘッダ */}
      <header
        className="flex items-center justify-between px-4 py-2 border-b"
        style={{ borderColor: tokens.divider }}
      >
        <span
          className="text-[10px] font-semibold tracking-[0.18em] uppercase"
          style={{ color: tokens.textMuted }}
        >
          {t('prediction.coach_summary') || 'コーチ向けサマリー'}
        </span>
        <span className="text-[10px]" style={{ color: tokens.textFaint }}>
          {t('analysis.sample_size', { count: sampleSize })}
        </span>
      </header>

      {/* 本体 grid: PowerPoint 流に左から「最重要 → 補助」 */}
      <div className="grid grid-cols-2 sm:grid-cols-5">
        {/* 1. 勝率 (最重要、最大の数字) — A/B/中立 で意味色 */}
        <Cell tokens={tokens} label={t('prediction.win_probability') || '予測勝率'} divide>
          <div className="flex items-baseline gap-1">
            <span
              className="text-[28px] font-bold leading-none tabular-nums"
              style={{ color: winColorVal }}
            >
              {winPct}
            </span>
            <span className="text-xs" style={{ color: tokens.textMuted }}>%</span>
          </div>
          {recentForm && recentForm.sample > 0 && (
            <RecentForm trend={recentForm.trend} tokens={tokens} />
          )}
        </Cell>

        {/* 2. 信頼度 — 数値 + バー (色ではなく長さで読む) */}
        <Cell tokens={tokens} label={t('prediction.confidence') || '信頼度'} divide>
          <div className="flex items-baseline gap-1">
            <span
              className="text-[20px] font-semibold leading-none tabular-nums"
              style={{ color: tokens.textStrong }}
            >
              {confPct}
            </span>
            <span className="text-xs" style={{ color: tokens.textMuted }}>%</span>
            <span className="ml-1 text-xs" style={{ color: tokens.textFaint }}>
              {confidenceStars}
            </span>
          </div>
          {/* 信頼度バー (色は中立、長さで情報を運ぶ) */}
          <div
            className="mt-1.5 h-1 rounded-full overflow-hidden"
            style={{ backgroundColor: tokens.divider }}
          >
            <div
              className="h-full"
              style={{
                width: `${Math.max(0, Math.min(100, confPct))}%`,
                backgroundColor: tokens.textMuted,
              }}
            />
          </div>
          {lowSample && (
            <p
              className="mt-1 text-[10px]"
              style={{ color: B_BAD }}
              title={t('auto.CoachSummaryStrip.k2')}
            >
              {t('auto.CoachSummaryStrip.k1') || '※ サンプル少'}
            </p>
          )}
        </Cell>

        {/* 3. 最頻結果 — 中立 (良し悪し含意なし) */}
        <Cell tokens={tokens} label={t('prediction.most_likely') || '最頻結果'} divide>
          <span
            className="text-[20px] font-semibold leading-none tabular-nums"
            style={{ color: tokens.textStrong }}
          >
            {topResult}
          </span>
        </Cell>

        {/* 4. 最大リスク — B_BAD (警告として色を意味付け) */}
        <Cell tokens={tokens} label={t('prediction.biggest_risk') || '最大リスク'} divide>
          {topRisk ? (
            <p
              className="text-xs font-medium leading-snug line-clamp-2"
              style={{ color: B_BAD }}
              title={topRisk}
            >
              {topRisk}
            </p>
          ) : (
            <p className="text-xs" style={{ color: tokens.textFaint }}>—</p>
          )}
        </Cell>

        {/* 5. 推奨アクション — 中立 (戦術指示は良し悪し含意なし) */}
        <Cell tokens={tokens} label={t('prediction.top_action') || '推奨アクション'}>
          {topAction ? (
            <p
              className="text-xs font-medium leading-snug line-clamp-2"
              style={{ color: tokens.textPrimary }}
              title={topAction}
            >
              {topAction}
            </p>
          ) : (
            <p className="text-xs" style={{ color: tokens.textFaint }}>—</p>
          )}
        </Cell>
      </div>
    </section>
  )
}

/**
 * 5 セルの 1 つを描画。右に縦罫線 (divide) で区切る。
 * 内側余白・タイポグラフィを統一して PowerPoint 流の整列感を作る。
 */
function Cell({
  tokens, label, divide, children,
}: {
  tokens: Tokens
  label: string
  divide?: boolean
  children: React.ReactNode
}) {
  const { t } = useTranslation()

  return (
    <div
      className={`px-4 py-3 ${divide ? 'sm:border-r' : ''}`}
      style={divide ? { borderColor: tokens.divider } : undefined}
    >
      <p
        className="text-[10px] mb-1.5 tracking-wide"
        style={{ color: tokens.textMuted }}
      >
        {label}
      </p>
      {children}
    </div>
  )
}

/**
 * 最近のフォーム表示。↑↓→ で方向を示し、色は A/B の符号のみ。
 * 形状でも識別できるので色弱対応。
 */
function RecentForm({
  trend, tokens,
}: {
  trend: 'improving' | 'declining' | 'stable'
  tokens: Tokens
}) {
  const { t } = useTranslation()

  const map = {
    improving: { glyph: '↑', color: A_GOOD,  label: t('auto.CoachSummaryStrip.k3') },
    declining: { glyph: '↓', color: B_BAD,   label: t('auto.CoachSummaryStrip.k4') },
    stable:    { glyph: '→', color: tokens.textMuted, label: t('auto.CoachSummaryStrip.k5') },
  } as const
  const cfg = map[trend]
  return (
    <p className="mt-1 text-[10px] inline-flex items-center gap-0.5" style={{ color: cfg.color }}>
      <span aria-hidden="true">{cfg.glyph}</span>
      <span>{cfg.label}</span>
    </p>
  )
}

