// コンフォーマル予測カード（RESEARCH ティア · アナリスト・コーチ専用）
//
// 設計原則:
//   - プレイヤーロールには絶対に表示しない (ページレベルで RoleGuard 済み)
//   - 分布フリーカバレッジ保証（実測カバレッジ vs 目標カバレッジ）を主軸に置く
//   - 不確実性を必ず提示 (insufficient 状態を隠さない)
//   - 数値・バッジ・チップのみ。数式・手法説明は表示しない
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchConformal, ConformalGroup } from '@/api/conformal'
import { EvidenceBadge } from '@/components/dashboard/EvidenceBadge'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { MIcon } from '@/components/common/MIcon'
import { useCardTheme } from '@/hooks/useCardTheme'

// ── props ────────────────────────────────────────────────────────────────────

interface Props {
  playerId: number
}

// ── 定数: alpha 選択肢 ───────────────────────────────────────────────────────

const ALPHA_OPTIONS = [0.05, 0.1, 0.2] as const
type Alpha = (typeof ALPHA_OPTIONS)[number]

// ── ヘルパー ─────────────────────────────────────────────────────────────────

function pct1(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

/** "early|receiver|smash" を 3 パーツに分解する */
function splitGroupKey(key: string): { phase: string; role: string; shot: string } {
  const [phase = '', role = '', shot = ''] = key.split('|')
  return { phase, role, shot }
}

// ── サブコンポーネント: カバレッジ保証ヘッドライン ───────────────────────────

function CoverageHeadline({
  targetCoverage,
  empiricalCoverage,
  avgSetSize,
  met,
  t,
  textHeading,
  textMuted,
  textFaint,
  border,
  cardInner,
}: {
  targetCoverage: number
  empiricalCoverage: number
  avgSetSize: number
  met: boolean
  t: ReturnType<typeof useTranslation>['t']
  textHeading: string
  textMuted: string
  textFaint: string
  border: string
  cardInner: string
}) {
  return (
    <div className={`rounded-ss-md p-3 space-y-2 border ${border} ${cardInner}`}>
      {/* 保証ラベル */}
      <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
        {t('auto.ConformalCard.coverage_section_label')}
      </p>

      {/* 目標 vs 実測 */}
      <div className="flex items-center gap-4 flex-wrap">
        {/* 目標カバレッジ */}
        <div className="flex flex-col items-center gap-0.5">
          <span className={`text-[10px] ${textFaint}`}>{t('auto.ConformalCard.target_label')}</span>
          <span className={`text-lg font-bold font-mono ss-num ${textMuted}`}>{pct1(targetCoverage)}</span>
        </div>

        {/* 矢印区切り */}
        <MIcon name="arrow_forward" size={16} className={textFaint} />

        {/* 実測カバレッジ */}
        <div className="flex flex-col items-center gap-0.5">
          <span className={`text-[10px] ${textFaint}`}>{t('auto.ConformalCard.empirical_label')}</span>
          <span
            className={`text-lg font-bold font-mono ss-num`}
            style={{ color: met ? '#34d399' : '#f87171' }}
          >
            {pct1(empiricalCoverage)}
          </span>
        </div>

        {/* 保証アイコン */}
        <div className="flex items-center gap-1 ml-auto">
          {met ? (
            <MIcon name="check_circle" size={20} className="text-emerald-400" />
          ) : (
            <MIcon name="cancel" size={20} className="text-red-400" />
          )}
          <span
            className={`text-[11px] font-semibold`}
            style={{ color: met ? '#34d399' : '#f87171' }}
          >
            {met
              ? t('auto.ConformalCard.guarantee_met')
              : t('auto.ConformalCard.guarantee_not_met')}
          </span>
        </div>
      </div>

      {/* 平均セットサイズ */}
      <p className={`text-[11px] ss-num ${textMuted}`}>
        {t('auto.ConformalCard.avg_set_size', { v: avgSetSize.toFixed(2) })}
      </p>

      {/* 保証の解釈ヒント */}
      <p className={`text-[10px] ${textFaint}`}>
        {t('auto.ConformalCard.coverage_hint')}
      </p>
    </div>
  )
}

// ── サブコンポーネント: 予測セットチップ ────────────────────────────────────

function PredictionSetChips({
  predictionSet,
  t,
}: {
  predictionSet: Array<'win' | 'loss'>
  t: ReturnType<typeof useTranslation>['t']
}) {
  const isAbstain = predictionSet.includes('win') && predictionSet.includes('loss')
  const isWin = !isAbstain && predictionSet.includes('win')
  const isLoss = !isAbstain && predictionSet.includes('loss')

  if (isAbstain) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-ss-pill bg-gray-500/20 text-gray-400">
        <MIcon name="help_outline" size={10} />
        {t('auto.ConformalCard.set_abstain')}
      </span>
    )
  }
  if (isWin) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-ss-pill bg-emerald-500/15 text-emerald-400">
        <MIcon name="trending_up" size={10} />
        {t('auto.ConformalCard.set_win')}
      </span>
    )
  }
  if (isLoss) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-ss-pill bg-red-500/15 text-red-400">
        <MIcon name="trending_down" size={10} />
        {t('auto.ConformalCard.set_loss')}
      </span>
    )
  }
  return null
}

// ── サブコンポーネント: グループ行 ──────────────────────────────────────────

function GroupRow({
  row,
  phaseLabel,
  roleLabel,
  shotLabel,
  t,
  border,
  textMuted,
  textFaint,
  cardInner,
}: {
  row: ConformalGroup
  phaseLabel: string
  roleLabel: string
  shotLabel: string
  t: ReturnType<typeof useTranslation>['t']
  border: string
  textMuted: string
  textFaint: string
  cardInner: string
}) {
  return (
    <div className={`rounded-ss-md p-2.5 border ${border} ${cardInner}`}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        {/* ラベル群 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-ss-pill bg-blue-500/15 text-blue-400">
            {phaseLabel}
          </span>
          <span className={`text-[11px] px-1.5 py-0.5 rounded-ss-pill bg-gray-500/15 ${textFaint}`}>
            {roleLabel}
          </span>
          <span className={`text-[11px] px-1.5 py-0.5 rounded-ss-pill bg-purple-500/10 text-purple-400`}>
            {shotLabel}
          </span>
        </div>

        {/* 右側: p_win + N */}
        <div className="flex items-center gap-3">
          <span className={`text-[11px] font-mono font-semibold ss-num ${textMuted}`}>
            {pct1(row.p_win)}
          </span>
          <span className={`text-[10px] ss-num ${textFaint}`}>
            {t('auto.ConformalCard.n_only', { n: row.n })}
          </span>
        </div>
      </div>

      {/* 予測セットチップ */}
      <div className="mt-1.5">
        <PredictionSetChips predictionSet={row.prediction_set} t={t} />
      </div>
    </div>
  )
}

// ── サブコンポーネント: alpha トグル ────────────────────────────────────────

function AlphaToggle({
  value,
  onChange,
  textFaint,
}: {
  value: Alpha
  onChange: (a: Alpha) => void
  textFaint: string
}) {
  return (
    <div className="flex items-center gap-1">
      {ALPHA_OPTIONS.map((a) => (
        <button
          key={a}
          onClick={() => onChange(a)}
          className={`text-[10px] px-2 py-0.5 rounded-ss-pill border transition-colors duration-fast ${
            value === a
              ? 'border-blue-500 bg-blue-500/15 text-blue-400'
              : `border-transparent bg-gray-500/10 ${textFaint} hover:bg-gray-500/20`
          }`}
        >
          α={a}
        </button>
      ))}
    </div>
  )
}

// ── メインコンポーネント ───────────────────────────────────────────────────────

export function ConformalCard({ playerId }: Props) {
  const { t } = useTranslation()
  const {
    card,
    textHeading,
    textMuted,
    textFaint,
    border,
    cardInner,
    loading,
  } = useCardTheme()

  const [alpha, setAlpha] = useState<Alpha>(0.1)

  // スコアフェーズ・役割ラベルは t() 経由。useMemo で t の変更に追従する
  const PHASE_LABELS = useMemo<Record<string, string>>(
    () => ({
      early: t('auto.ConformalCard.phase_early'),
      mid: t('auto.ConformalCard.phase_mid'),
      deuce: t('auto.ConformalCard.phase_deuce'),
      endgame: t('auto.ConformalCard.phase_endgame'),
    }),
    [t],
  )

  const ROLE_LABELS = useMemo<Record<string, string>>(
    () => ({
      server: t('auto.ConformalCard.role_server'),
      receiver: t('auto.ConformalCard.role_receiver'),
    }),
    [t],
  )

  /** shot_types i18n キーへのフォールバック付きルックアップ */
  const shotLabel = useMemo(
    () =>
      (bucket: string): string => {
        const key = `shot_types.${bucket}`
        const translated = t(key)
        // i18next はキーが見つからない場合 key 自体を返す
        return translated === key ? bucket : translated
      },
    [t],
  )

  const { data, isLoading, isError } = useQuery({
    queryKey: ['conformal', playerId, alpha],
    queryFn: () => fetchConformal(playerId, alpha),
    enabled: !!playerId,
  })

  const confData = data?.data
  const meta = data?.meta

  // データ不足判定
  const isInsufficient =
    !confData ||
    confData.status === 'insufficient' ||
    confData.empirical_coverage == null

  const groups = confData?.per_group ?? []

  return (
    <div className={`${card} rounded-ss-lg shadow-card p-4 space-y-3`}>
      {/* ─ ヘッダ ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className={`text-sm font-semibold ${textHeading} flex items-center gap-1.5`}>
          <MIcon name="verified" size={16} />
          {t('auto.ConformalCard.title')}
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
        caution={t('auto.ConformalCard.caution')}
        assumptions={t('auto.ConformalCard.assumptions')}
        promotionCriteria={t('auto.ConformalCard.promotion_criteria')}
      />

      {/* ─ alpha トグル ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`text-[10px] ${textFaint}`}>
          {t('auto.ConformalCard.alpha_label')}
        </span>
        <AlphaToggle value={alpha} onChange={setAlpha} textFaint={textFaint} />
      </div>

      {/* ─ ローディング ── */}
      {isLoading && (
        <p className={`text-sm text-center py-4 ${loading}`}>
          {t('auto.ConformalCard.loading')}
        </p>
      )}

      {/* ─ エラー ── */}
      {isError && !isLoading && (
        <p className="text-sm text-center py-4 text-red-400">
          {t('auto.ConformalCard.error')}
        </p>
      )}

      {/* ─ データあり ── */}
      {!isLoading && !isError && data && (
        <>
          {/* ─ データ不足 ── */}
          {isInsufficient ? (
            <div className={`rounded-ss-md p-3 border ${border} ${cardInner} opacity-60`}>
              <div className="flex items-center gap-1.5">
                <MIcon name="info" size={14} className="text-amber-400 shrink-0" />
                <p className={`text-[11px] ss-num ${textMuted}`}>
                  {t('auto.ConformalCard.insufficient', {
                    n: confData?.n_total ?? 0,
                  })}
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* ─ カバレッジ保証ヘッドライン ── */}
              <CoverageHeadline
                targetCoverage={confData!.target_coverage}
                empiricalCoverage={confData!.empirical_coverage!}
                avgSetSize={confData!.avg_set_size}
                met={confData!.validation.coverage_guarantee_met}
                t={t}
                textHeading={textHeading}
                textMuted={textMuted}
                textFaint={textFaint}
                border={border}
                cardInner={cardInner}
              />

              {/* ─ サマリ行 (サンプル数 / 信頼度) ── */}
              <div className={`rounded-ss-md p-2.5 border ${border} ${cardInner}`}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className={`text-[11px] ss-num ${textMuted}`}>
                    {t('auto.ConformalCard.sample_summary', {
                      total: confData!.n_total,
                      calib: confData!.n_calibration,
                      test: confData!.n_test,
                    })}
                  </span>
                  <ConfidenceBadge sampleSize={meta?.sample_size ?? 0} compact />
                </div>
              </div>

              {/* ─ グループ別予測 ── */}
              {groups.length > 0 && (
                <div className="space-y-1.5">
                  <p className={`text-[10px] font-medium uppercase tracking-wider ${textFaint}`}>
                    {t('auto.ConformalCard.group_header', { n: groups.length })}
                  </p>
                  {groups.map((row) => {
                    const { phase, role, shot } = splitGroupKey(row.group)
                    return (
                      <GroupRow
                        key={row.group}
                        row={row}
                        phaseLabel={PHASE_LABELS[phase] ?? phase}
                        roleLabel={ROLE_LABELS[role] ?? role}
                        shotLabel={shotLabel(shot)}
                        t={t}
                        border={border}
                        textMuted={textMuted}
                        textFaint={textFaint}
                        cardInner={cardInner}
                      />
                    )
                  })}
                </div>
              )}

              {groups.length === 0 && (
                <p className={`text-sm text-center py-2 ${loading}`}>
                  {t('auto.ConformalCard.no_groups')}
                </p>
              )}
            </>
          )}

          <p className={`text-[10px] ${textFaint}`}>
            {t('auto.ConformalCard.footnote')}
          </p>
        </>
      )}
    </div>
  )
}
