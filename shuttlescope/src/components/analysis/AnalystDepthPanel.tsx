/**
 * AnalystDepthPanel — Phase 1 Rebuild: アナリスト深掘り予測パネル
 *
 * 直近フォーム / 成長トレンド / ブライアスコア /
 * 最近傍試合エビデンス / 特徴量ブレンド内訳
 *
 * RoleGuard: analyst のみ
 */
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { NoDataMessage } from '@/components/common/NoDataMessage'
import { RoleGuard } from '@/components/common/RoleGuard'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { WIN, LOSS } from '@/styles/colors'

// ── 型定義 ──────────────────────────────────────────────────────────────────

interface RecentForm {
  win_rate: number
  sample: number
  trend: 'improving' | 'declining' | 'stable'
  results: string[]
  overall_wr: number
}

interface GrowthBucket {
  label: string
  win_rate: number
  sample: number
}

interface GrowthTrend {
  buckets: GrowthBucket[]
  slope: number
  direction: 'up' | 'down' | 'flat'
  sample: number
}

interface BrierScore {
  score: number | null
  sample: number
  grade: 'good' | 'fair' | 'poor' | null
}

interface NearestMatch {
  date: string
  tournament_level: string
  result: 'win' | 'loss'
  score_summary: string
  similarity_score: number
}

interface FeatureBreakdown {
  base_wr: number
  recent_wr: number
  h2h_wr: number | null
  weights: Record<string, number>
  obs_modifier: number
  raw_blend: number
  final: number
}

interface AnalystDepthData {
  recent_form: RecentForm
  growth_trend: GrowthTrend
  brier_score: BrierScore
  nearest_match_evidence: NearestMatch[]
  set_model_type: 'observed' | 'momentum'
  feature_breakdown: FeatureBreakdown
  win_prob_v1: number
  win_prob_v2: number
}

interface Props {
  playerId: number
  opponentId?: number | null
  tournamentLevel?: string
}

// ── サブコンポーネント ────────────────────────────────────────────────────────

function RecentFormSection({ data, isLight }: { data: RecentForm; isLight: boolean }) {
  const { t } = useTranslation()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  const trendColor =
    data.trend === 'improving' ? WIN
    : data.trend === 'declining' ? LOSS
    : subText

  const trendLabel =
    data.trend === 'improving' ? t('prediction.recent_form_improving')
    : data.trend === 'declining' ? t('prediction.recent_form_declining')
    : t('prediction.recent_form_stable')

  return (
    <div>
      <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
        {t('prediction.recent_form')}
      </p>
      <div className="flex items-center gap-3 flex-wrap">
        {/* スパークライン */}
        <div className="flex items-end gap-0.5">
          {data.results.map((r, i) => (
            <div
              key={i}
              title={r === 'W' ? '勝' : '負'}
              style={{
                width: 10,
                height: r === 'W' ? 20 : 12,
                backgroundColor: r === 'W' ? WIN : LOSS,
                borderRadius: 2,
                opacity: 0.85,
              }}
            />
          ))}
          {data.results.length === 0 && (
            <span className="text-xs" style={{ color: subText }}>—</span>
          )}
        </div>

        {/* 数値 */}
        <div className="space-y-0.5">
          <p className="text-sm font-bold" style={{ color: trendColor }}>
            {trendLabel} <span className="font-normal text-xs" style={{ color: subText }}>直近{data.sample}試合</span>
          </p>
          <p className="text-xs" style={{ color: subText }}>
            直近勝率 {Math.round(data.win_rate * 100)}%
            <span className="ml-2">全体 {Math.round(data.overall_wr * 100)}%</span>
          </p>
        </div>
      </div>
    </div>
  )
}

function GrowthTrendSection({ data, isLight }: { data: GrowthTrend; isLight: boolean }) {
  const { t } = useTranslation()
  const subText = isLight ? '#64748b' : '#9ca3af'

  const dirLabel =
    data.direction === 'up' ? t('prediction.growth_direction_up')
    : data.direction === 'down' ? t('prediction.growth_direction_down')
    : t('prediction.growth_direction_flat')

  const dirColor =
    data.direction === 'up' ? WIN
    : data.direction === 'down' ? LOSS
    : subText

  if (data.buckets.length === 0) {
    return (
      <div>
        <p className="text-xs font-semibold mb-1" style={{ color: subText }}>
          {t('prediction.growth_trend')}
        </p>
        <NoDataMessage sampleSize={0} minRequired={4} unit="試合" />
      </div>
    )
  }

  const maxWR = Math.max(...data.buckets.map((b) => b.win_rate), 0.01)
  const BAR_MAX_H = 40

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-semibold" style={{ color: subText }}>
          {t('prediction.growth_trend')}
        </p>
        <p className="text-xs font-medium" style={{ color: dirColor }}>{dirLabel}</p>
      </div>
      <div className="flex items-end gap-1.5">
        {data.buckets.map((b, i) => (
          <div key={i} className="flex flex-col items-center gap-0.5" style={{ minWidth: 28 }}>
            <span className="text-[9px]" style={{ color: subText }}>
              {Math.round(b.win_rate * 100)}%
            </span>
            <div
              style={{
                height: Math.max(4, Math.round((b.win_rate / maxWR) * BAR_MAX_H)),
                width: 20,
                backgroundColor: b.win_rate >= 0.5 ? WIN + 'aa' : LOSS + 'aa',
                borderRadius: '2px 2px 0 0',
              }}
            />
            <span className="text-[9px]" style={{ color: subText }}>{b.label}</span>
          </div>
        ))}
      </div>
      <p className="text-[10px] mt-1" style={{ color: subText }}>
        傾き {data.slope > 0 ? '+' : ''}{(data.slope * 100).toFixed(1)}% / バケット
        <span className="ml-2">{data.sample}試合</span>
      </p>
    </div>
  )
}

function BrierScoreSection({ data, isLight }: { data: BrierScore; isLight: boolean }) {
  const { t } = useTranslation()
  const subText = isLight ? '#64748b' : '#9ca3af'

  if (data.score === null) {
    return (
      <div>
        <p className="text-xs font-semibold mb-1" style={{ color: subText }}>
          {t('prediction.brier_score')}
        </p>
        <p className="text-xs" style={{ color: subText }}>
          データ不足（{data.sample}試合 / 最低5試合必要）
        </p>
      </div>
    )
  }

  const gradeColor =
    data.grade === 'good' ? WIN
    : data.grade === 'fair' ? '#f59e0b'
    : LOSS

  const gradeLabel =
    data.grade === 'good' ? t('prediction.brier_grade_good')
    : data.grade === 'fair' ? t('prediction.brier_grade_fair')
    : t('prediction.brier_grade_poor')

  // スコアをバーで表示 (0–0.25 範囲でスケール; 0.25 以上は 100%)
  const barPct = Math.min(100, Math.round((data.score / 0.25) * 100))

  return (
    <div>
      <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
        {t('prediction.brier_score')}
      </p>
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <div className="h-2 bg-gray-700 rounded overflow-hidden">
            <div
              className="h-full rounded transition-all"
              style={{ width: `${barPct}%`, backgroundColor: gradeColor }}
            />
          </div>
          <div className="flex justify-between text-[9px] mt-0.5" style={{ color: subText }}>
            <span>良好 0.0</span>
            <span>0.25 要注意</span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className="text-sm font-bold font-mono" style={{ color: gradeColor }}>
            {data.score.toFixed(3)}
          </p>
          <p className="text-[10px]" style={{ color: gradeColor }}>{gradeLabel}</p>
        </div>
      </div>
      <p className="text-[10px] mt-1" style={{ color: subText }}>{data.sample}試合のLOO推定</p>
    </div>
  )
}

function NearestEvidenceSection({ data, isLight }: { data: NearestMatch[]; isLight: boolean }) {
  const { t } = useTranslation()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  if (data.length === 0) {
    return (
      <div>
        <p className="text-xs font-semibold mb-1" style={{ color: subText }}>
          {t('prediction.nearest_evidence')}
        </p>
        <p className="text-xs" style={{ color: subText }}>試合データなし</p>
      </div>
    )
  }

  return (
    <div>
      <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
        {t('prediction.nearest_evidence')}
      </p>
      <div className="space-y-1">
        {data.map((m, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span
              className="font-bold w-4 shrink-0"
              style={{ color: m.result === 'win' ? WIN : LOSS }}
            >
              {m.result === 'win' ? 'W' : 'L'}
            </span>
            <span className="shrink-0 text-[10px] font-mono" style={{ color: subText }}>
              {m.date.slice(0, 7)}
            </span>
            <span className="shrink-0" style={{ color: subText }}>
              {m.tournament_level}
            </span>
            <span className="font-mono ml-auto" style={{ color: neutral }}>
              {m.score_summary}
            </span>
            {/* 類似度ドット */}
            <div className="flex gap-0.5 shrink-0">
              {[0, 1, 2].map((d) => (
                <div
                  key={d}
                  style={{
                    width: 5, height: 5,
                    borderRadius: '50%',
                    backgroundColor: d < m.similarity_score ? '#60a5fa' : '#374151',
                  }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FeatureBreakdownSection({ data, isLight }: { data: FeatureBreakdown; isLight: boolean }) {
  const { t } = useTranslation()
  const subText = isLight ? '#64748b' : '#9ca3af'
  const neutral = isLight ? '#334155' : '#d1d5db'

  type WeightEntry = { label: string; wr: number; weight: number }
  const entries: WeightEntry[] = [
    { label: '全試合統計', wr: data.base_wr, weight: data.weights['base'] ?? 0 },
    { label: '直近フォーム', wr: data.recent_wr, weight: data.weights['recent'] ?? 0 },
    ...(data.h2h_wr !== null && data.weights['h2h']
      ? [{ label: '直接対戦', wr: data.h2h_wr, weight: data.weights['h2h'] }]
      : []),
  ]

  return (
    <div>
      <p className="text-xs font-semibold mb-2" style={{ color: subText }}>
        {t('prediction.feature_breakdown')}
      </p>
      <div className="space-y-1.5">
        {entries.map((e, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-20 shrink-0" style={{ color: subText }}>{e.label}</span>
            <div className="flex-1 h-1.5 bg-gray-700 rounded overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${Math.round(e.wr * 100)}%`,
                  backgroundColor: e.wr >= 0.5 ? WIN + 'cc' : LOSS + 'cc',
                }}
              />
            </div>
            <span className="w-10 text-right font-mono shrink-0" style={{ color: neutral }}>
              {Math.round(e.wr * 100)}%
            </span>
            <span className="w-10 text-right text-[10px] shrink-0" style={{ color: subText }}>
              ×{Math.round(e.weight * 100)}%
            </span>
          </div>
        ))}
        {data.obs_modifier !== 0 && (
          <div className="flex items-center gap-2 text-xs pt-1 border-t border-gray-700">
            <span className="w-20 shrink-0" style={{ color: subText }}>観察補正</span>
            <span
              className="font-mono"
              style={{ color: data.obs_modifier > 0 ? WIN : LOSS }}
            >
              {data.obs_modifier > 0 ? '+' : ''}{Math.round(data.obs_modifier * 100)}%
            </span>
          </div>
        )}
        <div className="flex items-center justify-between text-xs pt-1 border-t border-gray-700">
          <span style={{ color: subText }}>{t('prediction.win_prob_calibrated')}</span>
          <span className="font-bold font-mono" style={{ color: data.final >= 0.5 ? WIN : LOSS }}>
            {Math.round(data.final * 100)}%
          </span>
        </div>
      </div>
    </div>
  )
}

// ── メインコンポーネント ──────────────────────────────────────────────────────

function Inner({ playerId, opponentId, tournamentLevel }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const subText = isLight ? '#64748b' : '#9ca3af'

  const { data: resp, isLoading } = useQuery({
    queryKey: ['prediction-analyst-depth', playerId, opponentId, tournamentLevel],
    queryFn: () =>
      apiGet<{ success: boolean; data: AnalystDepthData }>('/prediction/analyst_depth', {
        player_id: playerId,
        ...(opponentId ? { opponent_id: opponentId } : {}),
        ...(tournamentLevel ? { tournament_level: tournamentLevel } : {}),
      }),
    enabled: !!playerId,
  })

  if (isLoading) {
    return <p className="text-xs text-gray-500 py-2">{t('prediction.loading')}</p>
  }

  const d = resp?.data
  if (!d) return null

  const sectionClass = 'border-t border-gray-700 pt-3 first:border-t-0 first:pt-0'

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-semibold tracking-widest uppercase" style={{ color: subText }}>
        {t('prediction.analyst_depth')}
      </p>

      <div className={sectionClass}>
        <RecentFormSection data={d.recent_form} isLight={isLight} />
      </div>

      <div className={sectionClass}>
        <GrowthTrendSection data={d.growth_trend} isLight={isLight} />
      </div>

      <div className={sectionClass}>
        <FeatureBreakdownSection data={d.feature_breakdown} isLight={isLight} />
      </div>

      <div className={sectionClass}>
        <BrierScoreSection data={d.brier_score} isLight={isLight} />
      </div>

      <div className={sectionClass}>
        <NearestEvidenceSection data={d.nearest_match_evidence} isLight={isLight} />
      </div>

      {/* セットモデルタイプ表示 */}
      <p className="text-[10px]" style={{ color: subText }}>
        セットモデル:{' '}
        {d.set_model_type === 'observed'
          ? t('prediction.set_model_observed')
          : t('prediction.set_model_momentum')}
        {'  '}
        v1勝率 {Math.round(d.win_prob_v1 * 100)}% →
        キャリブレーション済み {Math.round(d.win_prob_v2 * 100)}%
      </p>
    </div>
  )
}

export function AnalystDepthPanel({ playerId, opponentId, tournamentLevel }: Props) {
  return (
    <RoleGuard allowedRoles={['analyst']}>
      <Inner playerId={playerId} opponentId={opponentId} tournamentLevel={tournamentLevel} />
    </RoleGuard>
  )
}
