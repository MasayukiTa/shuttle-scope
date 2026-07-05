import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiGet } from '@/api/client'
import { CoGTimeline, CoGPoint } from '@/components/analysis/CoGTimeline'
import { MIcon } from '@/components/common/MIcon'

interface MatchSummary {
  match_id: number
  title: string
}

interface CoGResponse {
  stroke_id: number
  points: CoGPoint[]
}

export function CoGDetectionPage({ onBack }: { onBack?: () => void } = {}) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [matchId, setMatchId] = useState<number | null>(null)
  const [strokeId, setStrokeId] = useState<number | null>(null)
  const [side, setSide] = useState<string | undefined>(undefined)

  const bgBase = 'bg-[var(--ss-bg-app)] text-[var(--ss-t1)]'
  const panelBg = 'bg-[var(--ss-surface-1)] border-[var(--ss-border)]'
  const selectCls = 'rounded-[5px] border-[var(--ss-border-strong)] px-3 py-2 text-sm bg-[var(--ss-surface-1)] text-[var(--ss-t1)] border'

  // 試合一覧取得
  const matchesQuery = useQuery<MatchSummary[]>({
    queryKey: ['cog', 'matches'],
    queryFn: () => apiGet('/v1/expert/videos'),
  })

  // 試合内ストローク一覧取得（expert clips エンドポイントを再利用）
  const clipsQuery = useQuery<{ clips: { stroke_id: number; rally_context: { shot_type?: string } }[] }>({
    queryKey: ['cog', 'clips', matchId],
    queryFn: () => apiGet('/v1/expert/clips', { match_id: matchId! }),
    enabled: !!matchId,
  })

  // CoG データ取得
  const cogQuery = useQuery<CoGResponse>({
    queryKey: ['cog', 'data', strokeId],
    queryFn: () => apiGet('/v1/analysis/cog', { stroke_id: strokeId! }),
    enabled: !!strokeId,
    retry: false,
  })

  const clips = clipsQuery.data?.clips ?? []
  const points = cogQuery.data?.points ?? []

  return (
    <div className={`h-full w-full overflow-y-auto ${bgBase}`}>
      <div className="max-w-5xl mx-auto p-4 md:p-6">
        <header className="flex items-center gap-4 mb-6 flex-wrap">
          <button
            className="px-4 py-2 rounded-[5px] text-sm border border-[var(--ss-border)] hover:bg-[var(--ss-surface-2)]"
            onClick={() => onBack ? onBack() : navigate(-1)}
          >
            ← {t('cog_detection.back')}
          </button>
          <div>
            <h1 className="text-xl font-bold text-[var(--ss-t1)]">{t('cog_detection.title')}</h1>
            <p className="text-sm text-[var(--ss-t2)]">
              {t('cog_detection.subtitle')}
            </p>
          </div>
        </header>

        {/* 絞り込みコントロール */}
        <div className={`rounded-lg border p-4 mb-6 ${panelBg}`}>
          <div className="flex flex-wrap gap-4 items-end">
            {/* 試合選択 */}
            <div>
              <label className="text-xs font-semibold block mb-1">{t('auto.CoGDetectionPage.k1')}</label>
              <select
                className={selectCls}
                value={matchId ?? ''}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  setMatchId(v || null)
                  setStrokeId(null)
                }}
              >
                <option value="">{t('auto.CoGDetectionPage.k2')}</option>
                {(matchesQuery.data ?? []).map((m) => (
                  <option key={m.match_id} value={m.match_id}>{m.title}</option>
                ))}
              </select>
            </div>

            {/* ストローク選択 */}
            <div>
              <label className="text-xs font-semibold block mb-1">{t('auto.CoGDetectionPage.k3')}</label>
              <select
                className={selectCls}
                value={strokeId ?? ''}
                onChange={(e) => setStrokeId(Number(e.target.value) || null)}
                disabled={!matchId || clips.length === 0}
              >
                <option value="">{t('auto.CoGDetectionPage.k4')}</option>
                {clips.map((c) => (
                  <option key={c.stroke_id} value={c.stroke_id}>
                    #{c.stroke_id}
                    {c.rally_context?.shot_type ? ` (${c.rally_context.shot_type})` : ''}
                  </option>
                ))}
              </select>
            </div>

            {/* サイドフィルタ */}
            <div>
              <label className="text-xs font-semibold block mb-1">{t('auto.CoGDetectionPage.k5')}</label>
              <select
                className={selectCls}
                value={side ?? ''}
                onChange={(e) => setSide(e.target.value || undefined)}
              >
                <option value="">{t('auto.CoGDetectionPage.k6')}</option>
                <option value="left">{t('auto.CoGDetectionPage.left')}</option>
                <option value="right">{t('auto.CoGDetectionPage.right')}</option>
              </select>
            </div>
          </div>
        </div>

        {/* CoG ビジュアライゼーション */}
        <div className={`rounded-[6px] border p-4 ${panelBg}`}>
          {!strokeId && (
            <div className="flex items-center justify-center h-48 text-sm text-[var(--ss-t3)]">
              {t('cog_detection.select_stroke')}
            </div>
          )}
          {strokeId && cogQuery.isLoading && (
            <div className="flex items-center justify-center h-48 text-sm text-[var(--ss-t3)]">
              {t('cog_detection.loading')}
            </div>
          )}
          {strokeId && !cogQuery.isLoading && (
            <>
              {points.length < 10 && points.length > 0 && (
                <p className="text-xs text-[var(--ss-warn)] mb-2 inline-flex items-center gap-1"><MIcon name="warning" size={12} />{t('cog_detection.sample_warning')}</p>
              )}
              <CoGTimeline
                points={points}
                side={side}
                width={720}
                height={200}
                className="mx-auto"
              />

              {/* 統計サマリ */}
              {points.length > 0 && (
                <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
                  {[
                    { label: t('cog_detection.left_weight'),  value: (points.reduce((s, p) => s + p.left_pct, 0) / points.length * 100).toFixed(1) + '%' },
                    { label: t('cog_detection.right_weight'), value: (points.reduce((s, p) => s + p.right_pct, 0) / points.length * 100).toFixed(1) + '%' },
                    { label: t('cog_detection.forward_lean'), value: (points.reduce((s, p) => s + p.forward_lean, 0) / points.length).toFixed(3) },
                    { label: t('cog_detection.stability'),    value: (points.reduce((s, p) => s + p.stability_score, 0) / points.length).toFixed(3) },
                  ].map((item) => (
                    <div key={item.label} className="rounded-[5px] border border-[var(--ss-border)] p-3 text-center bg-[var(--ss-surface-2)]">
                      <div className="text-xs text-[var(--ss-t2)] mb-1">{item.label}</div>
                      <div className="text-lg font-bold ss-num text-[var(--ss-t1)]">{item.value}</div>
                    </div>
                  ))}
                </div>
              )}

              {points.length === 0 && (
                <div className="flex items-center justify-center h-24 text-sm text-[var(--ss-t3)]">
                  {t('cog_detection.no_data')}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default CoGDetectionPage
