// DR-OPE ポリシー評価カード（RESEARCH ティア · アナリスト・コーチ専用）
//
// 設計原則:
//   - プレイヤーロールには絶対に表示しない (ページレベルで RoleGuard 済み)
//   - 不確実性を必ず提示 (insufficient 状態を隠さない)
//   - 数値・バー・ラベルのみ。数式・手法説明は表示しない
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  fetchPolicyEval,
  PolicyEvalState,
  PolicyEvalStateOk,
} from '@/api/policyEval'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { MIcon } from '@/components/common/MIcon'
import { useCardTheme } from '@/hooks/useCardTheme'

// ── props ────────────────────────────────────────────────────────────────────

interface Props {
  playerId: number
}

// ── ヘルパー ─────────────────────────────────────────────────────────────────

function pct1(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

/** state_key "early|server" を phase と role に分解する */
function splitStateKey(key: string): { phase: string; role: string } {
  const [phase = '', role = ''] = key.split('|')
  return { phase, role }
}

/** 正数に + 記号を付ける */
function signedPct(v: number): string {
  const s = pct1(Math.abs(v))
  return v >= 0 ? `+${s}` : `-${s}`
}

/** 型ガード: ok 状態か */
function isOk(s: PolicyEvalState): s is PolicyEvalStateOk {
  return s.status === 'ok'
}

// ── サブコンポーネント: 横バー (0..1) ───────────────────────────────────────

function TinyBar({ value, color }: { value: number; color: string }) {
  const w = Math.max(0, Math.min(1, value))
  return (
    <div className="h-1.5 w-full rounded-full bg-[var(--ss-surface-2)]/40 overflow-hidden">
      <div className="h-full rounded-full transition-all duration-base ease-out" style={{ width: `${w * 100}%`, backgroundColor: color }} />
    </div>
  )
}

// ── サブコンポーネント: ok 状態の詳細行 ─────────────────────────────────────

function OkStateRow({
  row,
  phaseLabel,
  roleLabel,
  t,
  border,
  textMuted,
  textFaint,
  textHeading,
  textSecondary,
  cardInner,
}: {
  row: PolicyEvalStateOk
  phaseLabel: string
  roleLabel: string
  t: ReturnType<typeof useTranslation>['t']
  border: string
  textMuted: string
  textFaint: string
  textHeading: string
  textSecondary: string
  cardInner: string
}) {
  // uplift の絶対値を 0..1 にクランプしてバー幅にする (最大 ±50% = full bar)
  const barValue = Math.min(1, Math.abs(row.uplift) * 2)
  const upliftColor = row.uplift >= 0 ? '#34d399' : '#f87171'
  // CI 幅（大きいほど不確実）
  const ciWidth = row.ci_high - row.ci_low

  return (
    <div className={`rounded-ss-lg p-3 space-y-2 border ${border} ${cardInner}`}>
      {/* ─ ヘッダ行: 状態 + アップリフト + N ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-ss-sm bg-[rgba(37,99,235,0.15)] text-[var(--ss-brand)]">
            {phaseLabel}
          </span>
          <span className={`text-[11px] px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-surface-2)]/15 ${textFaint}`}>
            {roleLabel}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {/* アップリフト（見出し数値） */}
          <span
            className="text-base font-bold font-mono ss-num"
            style={{ color: upliftColor }}
          >
            {signedPct(row.uplift)}
          </span>
          <span className={`text-[10px] ${textFaint}`}>
            {t('auto.PolicyEvalCard.n_only', { n: row.n })}
          </span>
        </div>
      </div>

      {/* ─ アップリフトバー ── */}
      <TinyBar value={barValue} color={upliftColor} />

      {/* ─ 行動ポリシー → ターゲットポリシー ── */}
      <div className="flex gap-4 text-[11px] flex-wrap">
        <span className={textMuted}>
          {t('auto.PolicyEvalCard.value_behavior_label')}
          <span className={`ml-1 font-mono ss-num ${textSecondary}`}>{pct1(row.value_behavior)}</span>
        </span>
        <MIcon name="arrow_forward" size={12} className={textFaint} />
        <span className={textMuted}>
          {t('auto.PolicyEvalCard.value_target_label')}
          <span className={`ml-1 font-mono ss-num ${textHeading}`}>{pct1(row.value_target)}</span>
        </span>
      </div>

      {/* ─ CI 帯 ── */}
      <p className={`text-[10px] ss-num ${textFaint}`}>
        {t('auto.PolicyEvalCard.ci_range', {
          low: signedPct(row.ci_low),
          high: signedPct(row.ci_high),
          width: pct1(ciWidth),
        })}
      </p>
    </div>
  )
}

// ── サブコンポーネント: insufficient 状態行 ──────────────────────────────────

function InsufficientRow({
  row,
  phaseLabel,
  roleLabel,
  t,
  textFaint,
  border,
}: {
  row: PolicyEvalState
  phaseLabel: string
  roleLabel: string
  t: ReturnType<typeof useTranslation>['t']
  textFaint: string
  border: string
}) {
  return (
    <div className={`rounded-ss-lg p-2.5 border ${border} opacity-50`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className={`text-[10px] px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-surface-2)]/10 ${textFaint}`}>
            {phaseLabel}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-surface-2)]/10 ${textFaint}`}>
            {roleLabel}
          </span>
        </div>
        <span className={`text-[10px] ${textFaint}`}>
          {t('auto.PolicyEvalCard.insufficient', { n: row.n })}
        </span>
      </div>
    </div>
  )
}

// ── メインコンポーネント ───────────────────────────────────────────────────────

export function PolicyEvalCard({ playerId }: Props) {
  const { t } = useTranslation()
  const {
    card,
    textHeading,
    textSecondary,
    textMuted,
    textFaint,
    border,
    cardInner,
    loading,
  } = useCardTheme()

  // スコアフェーズ・役割ラベルは t() 経由。useMemo で t の変更に追従する
  const PHASE_LABELS = useMemo<Record<string, string>>(
    () => ({
      early: t('auto.PolicyEvalCard.phase_early'),
      mid: t('auto.PolicyEvalCard.phase_mid'),
      deuce: t('auto.PolicyEvalCard.phase_deuce'),
      endgame: t('auto.PolicyEvalCard.phase_endgame'),
    }),
    [t],
  )

  const ROLE_LABELS = useMemo<Record<string, string>>(
    () => ({
      server: t('auto.PolicyEvalCard.role_server'),
      receiver: t('auto.PolicyEvalCard.role_receiver'),
    }),
    [t],
  )

  const { data, isLoading, isError } = useQuery({
    queryKey: ['policyEval', playerId],
    queryFn: () => fetchPolicyEval(playerId),
    enabled: !!playerId,
  })

  const states = data?.data?.states ?? []
  const summary = data?.data?.summary
  const meta = data?.meta

  const okStates = states.filter(isOk)
  const insufficientStates = states.filter((s) => s.status === 'insufficient')

  // ベスト状態のラベル (summary から)
  const bestStateLabel = useMemo(() => {
    if (!summary?.best_state) return null
    const { phase, role } = splitStateKey(summary.best_state.state_key)
    return `${PHASE_LABELS[phase] ?? phase} / ${ROLE_LABELS[role] ?? role}`
  }, [summary, PHASE_LABELS, ROLE_LABELS])

  return (
    <div className={`${card} rounded-ss-lg p-4 space-y-3`}>
      {/* ─ ヘッダ ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className={`text-sm font-semibold ${textHeading} flex items-center gap-1.5`}>
          <MIcon name="policy" size={16} />
          {t('auto.PolicyEvalCard.title')}
        </h3>
        <EvidenceBadge
          tier="research"
          evidenceLevel="exploratory"
          sampleSize={meta?.sample_size}
          recommendationAllowed={false}
        />
      </div>

      {/* ─ 研究注意バナー ── */}
      <ResearchNotice
        caution={t('auto.PolicyEvalCard.caution')}
        assumptions={t('auto.PolicyEvalCard.assumptions')}
        promotionCriteria={t('auto.PolicyEvalCard.promotion_criteria')}
      />

      {/* ─ ローディング ── */}
      {isLoading && (
        <p className={`text-sm text-center py-4 ${loading}`}>
          {t('auto.PolicyEvalCard.loading')}
        </p>
      )}

      {/* ─ エラー ── */}
      {isError && !isLoading && (
        <p className="text-sm text-center py-4 text-red-400">
          {t('auto.PolicyEvalCard.error')}
        </p>
      )}

      {/* ─ データあり ── */}
      {!isLoading && !isError && data && (
        <>
          {/* サマリブロック */}
          {summary && (
            <div className={`rounded-ss-lg p-3 space-y-1.5 border ${border} ${cardInner}`}>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <span className={`text-[11px] font-medium ss-num ${textMuted}`}>
                  {t('auto.PolicyEvalCard.summary_states', {
                    analyzed: summary.states_analyzed,
                    insufficient: summary.states_insufficient,
                  })}
                </span>
                <ConfidenceBadge sampleSize={meta?.sample_size ?? 0} compact />
              </div>
              {/* ベスト機会の強調表示 */}
              {bestStateLabel && summary.best_state && (
                <p className="text-[11px] font-medium text-[var(--ss-success)]">
                  <MIcon name="star" size={12} className="align-middle mr-0.5" />
                  {t('auto.PolicyEvalCard.best_opportunity', {
                    state: bestStateLabel,
                    uplift: signedPct(summary.best_state.uplift),
                  })}
                </p>
              )}
            </div>
          )}

          {/* データなし */}
          {okStates.length === 0 && insufficientStates.length === 0 && (
            <p className={`text-sm text-center py-4 ${loading}`}>
              {t('auto.PolicyEvalCard.empty')}
            </p>
          )}

          {/* ok 状態の詳細カード */}
          {okStates.length > 0 && (
            <div className="space-y-2">
              <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
                {t('auto.PolicyEvalCard.ok_states_header', { n: okStates.length })}
              </p>
              {okStates.map((row) => {
                const { phase, role } = splitStateKey(row.state_key)
                return (
                  <OkStateRow
                    key={row.state_key}
                    row={row}
                    phaseLabel={PHASE_LABELS[phase] ?? phase}
                    roleLabel={ROLE_LABELS[role] ?? role}
                    t={t}
                    border={border}
                    textMuted={textMuted}
                    textFaint={textFaint}
                    textHeading={textHeading}
                    textSecondary={textSecondary}
                    cardInner={cardInner}
                  />
                )
              })}
            </div>
          )}

          {/* insufficient 状態（グレーアウト） */}
          {insufficientStates.length > 0 && (
            <div className="space-y-1.5">
              <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
                {t('auto.PolicyEvalCard.insufficient_header', { n: insufficientStates.length })}
              </p>
              {insufficientStates.map((row) => {
                const { phase, role } = splitStateKey(row.state_key)
                return (
                  <InsufficientRow
                    key={row.state_key}
                    row={row}
                    phaseLabel={PHASE_LABELS[phase] ?? phase}
                    roleLabel={ROLE_LABELS[role] ?? role}
                    t={t}
                    textFaint={textFaint}
                    border={border}
                  />
                )
              })}
            </div>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            {t('auto.PolicyEvalCard.footnote')}
          </p>
        </>
      )}
    </div>
  )
}
