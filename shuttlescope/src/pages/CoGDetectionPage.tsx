import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { apiGet } from '@/api/client'
import { CoGTimeline, CoGPoint } from '@/components/analysis/CoGTimeline'
import { useTheme } from '@/hooks/useTheme'

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
  const { theme } = useTheme()
  const navigate = useNavigate()
  const isLight = theme === 'light'

  const [matchId, setMatchId] = useState<number | null>(null)
  const [strokeId, setStrokeId] = useState<number | null>(null)
  const [side, setSide] = useState<string | undefined>(undefined)

  const bgBase = isLight ? 'bg-gray-50 text-gray-900' : 'bg-gray-900 text-gray-100'
  const panelBg = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'
  const selectCls = `rounded border px-3 py-2 text-sm ${
    isLight ? 'bg-white border-gray-300 text-gray-900' : 'bg-gray-800 border-gray-600 text-gray-100'
  }`

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
            className={`px-4 py-2 rounded text-sm border ${
              isLight ? 'border-gray-300 hover:bg-gray-100' : 'border-gray-600 hover:bg-gray-700'
            }`}
            onClick={() => onBack ? onBack() : navigate(-1)}
          >
            ← {t('cog_detection.back')}
          </button>
          <div>
            <h1 className="text-xl font-bold">{t('cog_detection.title')}</h1>
            <p className={`text-sm ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
              {t('cog_detection.subtitle')}
            </p>
          </div>
        </header>

        {/* 絞り込みコントロール */}
        <div className={`rounded-lg border p-4 mb-6 ${panelBg}`}>
          <div className="flex flex-wrap gap-4 items-end">
            {/* 試合選択 */}
            <div>
              <label className="text-xs font-semibold block mb-1">試合</label>
              <select
                className={selectCls}
                value={matchId ?? ''}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  setMatchId(v || null)
                  setStrokeId(null)
                }}
              >
                <option value="">-- 試合を選択 --</option>
                {(matchesQuery.data ?? []).map((m) => (
                  <option key={m.match_id} value={m.match_id}>{m.title}</option>
                ))}
              </select>
            </div>

            {/* ストローク選択 */}
            <div>
              <label className="text-xs font-semibold block mb-1">ストローク</label>
              <select
                className={selectCls}
                value={strokeId ?? ''}
                onChange={(e) => setStrokeId(Number(e.target.value) || null)}
                disabled={!matchId || clips.length === 0}
              >
                <option value="">-- ストロークを選択 --</option>
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
              <label className="text-xs font-semibold block mb-1">サイド</label>
              <select
                className={selectCls}
                value={side ?? ''}
                onChange={(e) => setSide(e.target.value || undefined)}
              >
                <option value="">両サイド</option>
                <option value="left">Left</option>
                <option value="right">Right</option>
              </select>
            </div>
          </div>
        </div>

        {/* CoG ビジュアライゼーション */}
        <div className={`rounded-lg border p-4 ${panelBg}`}>
          {!strokeId && (
            <div className={`flex items-center justify-center h-48 text-sm ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
              {t('cog_detection.select_stroke')}
            </div>
          )}
          {strokeId && cogQuery.isLoading && (
            <div className={`flex items-center justify-center h-48 text-sm ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
              {t('cog_detection.loading')}
            </div>
          )}
          {strokeId && !cogQuery.isLoading && (
            <>
              {points.length < 10 && points.length > 0 && (
                <p className="text-xs text-amber-500 mb-2">⚠ {t('cog_detection.sample_warning')}</p>
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
                    <div key={item.label} className={`rounded border p-3 text-center ${isLight ? 'border-gray-200' : 'border-gray-700'}`}>
                      <div className="text-xs mb-1">{item.label}</div>
                      <div className="text-lg font-bold">{item.value}</div>
                    </div>
                  ))}
                </div>
              )}

              {points.length === 0 && (
                <div className={`flex items-center justify-center h-24 text-sm ${isLight ? 'text-gray-400' : 'text-gray-500'}`}>
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
