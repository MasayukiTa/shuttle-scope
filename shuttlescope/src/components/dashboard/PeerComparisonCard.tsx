// Admin-only research-tier コミュニティ peer 比較カード。
//
// 安全性:
//   - role !== 'admin' の場合は何も render しない (フロント側 hard gate)。
//   - バックエンド側でも require_admin で 403、k-anonymity (N>=5)、demo 除外を強制。
//   - 個別選手の値は返らず、p25/p50/p75/mean/sd の集計値のみが表示される。
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useCardTheme } from '@/hooks/useCardTheme'
import { ResearchNotice } from '@/components/dashboard/ResearchNotice'

interface MetricAgg {
  p25: number
  p50: number
  p75: number
  mean: number
  sd: number
  unit: string
}

interface CohortStatsResponse {
  success: boolean
  data: {
    available: boolean
    n: number
    reason?: string
    metrics?: Record<string, MetricAgg>
  }
}

interface CohortSpec {
  age_bucket?: string
  level?: string
  handedness?: string
  gender?: string
  singles_doubles?: string
}

const AGE_BUCKETS = ['18-21', '22-25', '26-29', '30+']
const LEVELS: Array<{ value: string; key: string }> = [
  { value: 'local', key: 'local' },
  { value: 'regional', key: 'regional' },
  { value: 'national', key: 'national' },
  { value: 'international', key: 'international' },
]

export function PeerComparisonCard() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { card, textHeading, textMuted } = useCardTheme()

  const [cohort, setCohort] = useState<CohortSpec>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CohortStatsResponse['data'] | null>(null)

  if (role !== 'admin') {
    return null
  }

  const update = (key: keyof CohortSpec, value: string) => {
    setCohort((prev) => {
      const next = { ...prev }
      if (value) {
        next[key] = value
      } else {
        delete next[key]
      }
      return next
    })
  }

  const onCompute = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await apiPost<CohortStatsResponse>(
        '/analysis/research/peer_cohort_stats',
        cohort,
      )
      setResult(resp.data)
    } catch (_e) {
      setError(t('auto.PeerComparisonCard.error'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={`${card} rounded-ss-lg shadow-card p-4 space-y-3`}>
      <div className="flex items-center justify-between">
        <h2 className={`text-sm font-semibold ${textHeading}`}>
          {t('auto.PeerComparisonCard.title')}
        </h2>
      </div>

      <ResearchNotice caution={t('auto.PeerComparisonCard.banner')} />

      <div className="space-y-2">
        <div className={`text-xs font-semibold uppercase tracking-wider ${textMuted}`}>
          {t('auto.PeerComparisonCard.cohort_heading')}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <label className="text-xs space-y-1">
            <span className={textMuted}>{t('auto.PeerComparisonCard.age_bucket')}</span>
            <select
              className="w-full border border-[color:var(--ss-border-strong)] rounded-ss-md px-2 py-1 transition-colors duration-fast"
              value={cohort.age_bucket ?? ''}
              onChange={(e) => update('age_bucket', e.target.value)}
            >
              <option value="">{t('auto.PeerComparisonCard.any')}</option>
              {AGE_BUCKETS.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </label>
          <label className="text-xs space-y-1">
            <span className={textMuted}>{t('auto.PeerComparisonCard.level')}</span>
            <select
              className="w-full border border-[color:var(--ss-border-strong)] rounded-ss-md px-2 py-1 transition-colors duration-fast"
              value={cohort.level ?? ''}
              onChange={(e) => update('level', e.target.value)}
            >
              <option value="">{t('auto.PeerComparisonCard.any')}</option>
              {LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {t(`auto.PeerComparisonCard.${l.key}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs space-y-1">
            <span className={textMuted}>{t('auto.PeerComparisonCard.handedness')}</span>
            <select
              className="w-full border border-[color:var(--ss-border-strong)] rounded-ss-md px-2 py-1 transition-colors duration-fast"
              value={cohort.handedness ?? ''}
              onChange={(e) => update('handedness', e.target.value)}
            >
              <option value="">{t('auto.PeerComparisonCard.any')}</option>
              <option value="right">{t('auto.PeerComparisonCard.right')}</option>
              <option value="left">{t('auto.PeerComparisonCard.left')}</option>
            </select>
          </label>
          <label className="text-xs space-y-1">
            <span className={textMuted}>{t('auto.PeerComparisonCard.gender')}</span>
            <select
              className="w-full border border-[color:var(--ss-border-strong)] rounded-ss-md px-2 py-1 transition-colors duration-fast"
              value={cohort.gender ?? ''}
              onChange={(e) => update('gender', e.target.value)}
            >
              <option value="">{t('auto.PeerComparisonCard.any')}</option>
              <option value="m">{t('auto.PeerComparisonCard.male')}</option>
              <option value="f">{t('auto.PeerComparisonCard.female')}</option>
              <option value="other">{t('auto.PeerComparisonCard.other')}</option>
            </select>
          </label>
          <label className="text-xs space-y-1">
            <span className={textMuted}>{t('auto.PeerComparisonCard.singles_doubles')}</span>
            <select
              className="w-full border border-[color:var(--ss-border-strong)] rounded-ss-md px-2 py-1 transition-colors duration-fast"
              value={cohort.singles_doubles ?? ''}
              onChange={(e) => update('singles_doubles', e.target.value)}
            >
              <option value="">{t('auto.PeerComparisonCard.any')}</option>
              <option value="singles">{t('auto.PeerComparisonCard.singles')}</option>
              <option value="doubles">{t('auto.PeerComparisonCard.doubles')}</option>
            </select>
          </label>
        </div>
        <button
          type="button"
          onClick={onCompute}
          disabled={loading}
          className="px-3 py-1.5 rounded-ss-md bg-[color:var(--ss-brand)] hover:bg-[color:var(--ss-brand-hover)] text-white text-xs font-semibold disabled:opacity-50 transition-colors duration-fast"
        >
          {loading ? t('auto.PeerComparisonCard.loading') : t('auto.PeerComparisonCard.compute')}
        </button>
      </div>

      {error && <div className="text-xs text-[color:var(--ss-bad)]">{error}</div>}

      {result && !result.available && (
        <div className={`text-xs ${textMuted}`}>
          {t('auto.PeerComparisonCard.insufficient', { n: result.n })}
        </div>
      )}

      {result && result.available && (
        <div className="space-y-2">
          <span className="inline-block px-2 py-0.5 text-xs ss-num rounded-ss-sm bg-[color:var(--ss-brand)] text-white">
            {t('auto.PeerComparisonCard.n_chip', { n: result.n })}
          </span>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className={textMuted}>
                  <th className="text-left px-2 py-1">{t('auto.PeerComparisonCard.metric')}</th>
                  <th className="text-right px-2 py-1">{t('auto.PeerComparisonCard.p25')}</th>
                  <th className="text-right px-2 py-1">{t('auto.PeerComparisonCard.p50')}</th>
                  <th className="text-right px-2 py-1">{t('auto.PeerComparisonCard.p75')}</th>
                  <th className="text-right px-2 py-1">{t('auto.PeerComparisonCard.mean')}</th>
                  <th className="text-right px-2 py-1">{t('auto.PeerComparisonCard.sd')}</th>
                  <th className="text-right px-2 py-1">{t('auto.PeerComparisonCard.unit')}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(result.metrics ?? {}).map(([name, agg]) => (
                  <tr key={name} className="border-t border-[color:var(--ss-border)]">
                    <td className="text-left px-2 py-1">{name}</td>
                    <td className="text-right px-2 py-1 ss-num">{agg.p25}</td>
                    <td className="text-right px-2 py-1 ss-num">{agg.p50}</td>
                    <td className="text-right px-2 py-1 ss-num">{agg.p75}</td>
                    <td className="text-right px-2 py-1 ss-num">{agg.mean}</td>
                    <td className="text-right px-2 py-1 ss-num">{agg.sd}</td>
                    <td className="text-right px-2 py-1 ss-num">{agg.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
