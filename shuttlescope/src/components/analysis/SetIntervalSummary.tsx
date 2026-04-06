// K-003: セット間5秒サマリー（セット終了後ワンクリックで要約を表示）
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { X, ChevronRight, AlertTriangle } from 'lucide-react'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { RoleGuard } from '@/components/common/RoleGuard'
import { WIN, LOSS, BAR, LINE } from '@/styles/colors'

interface SetIntervalSummaryProps {
  setId: number
  playerAName: string
  playerBName: string
  onClose: () => void
  onNextSet: () => void
}

interface LossPattern {
  label: string
  count: number
  pct: number
}

interface ShotEntry {
  shot_type: string
  shot_type_ja: string
  win_rate?: number
  loss_rate?: number
  count: number
}

interface SetSummaryData {
  set_num: number
  score_a: number
  score_b: number
  winner: 'player_a' | 'player_b'
  total_rallies: number
  avg_rally_length: number
  rally_length_trend: 'short' | 'medium' | 'long'
  recent_loss_patterns: LossPattern[]
  effective_shots: ShotEntry[]
  risky_shots: ShotEntry[]
}

interface SetSummaryResponse {
  success: boolean
  data: SetSummaryData | null
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

const TREND_LABEL: Record<string, string> = {
  short: '短め（平均 4球未満）',
  medium: '標準（4〜8球）',
  long: '長め（8球超）',
}

export function SetIntervalSummary({
  setId,
  playerAName,
  playerBName,
  onClose,
  onNextSet,
}: SetIntervalSummaryProps) {
  const { t } = useTranslation()

  const { data: resp, isLoading } = useQuery({
    queryKey: ['set-summary', setId],
    queryFn: () => apiGet<SetSummaryResponse>('/analysis/set_summary', { set_id: setId }),
    staleTime: 0,
  })

  const sampleSize = resp?.meta?.sample_size ?? 0
  const data = resp?.data

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-700">
        {/* ヘッダー */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-white">
              {data ? `Set ${data.set_num} 終了` : 'セット終了サマリー'}
            </span>
            {data && (
              <span className="text-xs text-gray-400">
                {playerAName} <span style={{ color: data.winner === 'player_a' ? WIN : LOSS }} className="font-bold">{data.score_a}</span>
                {' — '}
                <span style={{ color: data.winner === 'player_b' ? WIN : LOSS }} className="font-bold">{data.score_b}</span> {playerBName}
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
            <X size={16} />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {isLoading && (
            <p className="text-gray-500 text-sm text-center py-4">{t('analysis.loading')}</p>
          )}

          {!isLoading && !data && (
            <p className="text-gray-500 text-sm text-center py-4">{t('analysis.no_data')}</p>
          )}

          {data && (
            <>
              {/* 信頼度バッジ */}
              <ConfidenceBadge sampleSize={sampleSize} />

              {/* 基本統計 */}
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-gray-700/50 rounded p-2">
                  <div className="text-[10px] text-gray-500 mb-0.5">ラリー数</div>
                  <div className="text-lg font-bold text-white">{data.total_rallies}</div>
                </div>
                <div className="bg-gray-700/50 rounded p-2">
                  <div className="text-[10px] text-gray-500 mb-0.5">平均球数</div>
                  <div className="text-lg font-bold text-white">{data.avg_rally_length}</div>
                </div>
                <div className="bg-gray-700/50 rounded p-2">
                  <div className="text-[10px] text-gray-500 mb-0.5">ラリー傾向</div>
                  <div className="text-xs font-semibold text-white">{TREND_LABEL[data.rally_length_trend]?.split('（')[0]}</div>
                </div>
              </div>

              {/* アナリスト・コーチ向け詳細 */}
              <RoleGuard
                allowedRoles={['analyst', 'coach']}
                fallback={
                  // 選手向け: 成長フレーミング
                  <div className="space-y-2">
                    <p className="text-xs text-gray-400 font-medium">{t('analysis.set_summary.growth_area')}</p>
                    {data.risky_shots.length === 0 ? (
                      <p className="text-xs text-gray-500">{t('analysis.no_data')}</p>
                    ) : (
                      <div className="space-y-1.5">
                        {data.risky_shots.map((s, i) => (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: LINE }} />
                            <span className="text-gray-300">{s.shot_type_ja} — {t('analysis.set_summary.growth_hint')}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                }
              >
                {/* 直近失点パターン */}
                {data.recent_loss_patterns.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-400 mb-2 flex items-center gap-1">
                      <AlertTriangle size={12} style={{ color: LOSS }} />
                      {t('analysis.set_summary.recent_loss_patterns')}（直近 10 失点）
                    </p>
                    <div className="space-y-1.5">
                      {data.recent_loss_patterns.slice(0, 3).map((p, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="text-gray-500 font-mono w-3 shrink-0">{i + 1}</span>
                          <span className="flex-1 text-gray-300 truncate">{p.label}</span>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <div className="w-16 bg-gray-700 rounded-full h-1.5">
                              <div className="h-1.5 rounded-full" style={{ width: `${(p.pct * 100).toFixed(0)}%`, backgroundColor: LOSS }} />
                            </div>
                            <span className="text-gray-400 w-8 text-right">{p.count}回</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 有効ショット / 注意ショット */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs font-semibold mb-1.5" style={{ color: WIN }}>
                      {t('analysis.set_summary.effective_shots')}
                    </p>
                    {data.effective_shots.length === 0 ? (
                      <p className="text-xs text-gray-600">{t('analysis.no_data')}</p>
                    ) : (
                      <div className="space-y-1">
                        {data.effective_shots.map((s, i) => (
                          <div key={i} className="flex items-center justify-between text-xs">
                            <span className="text-gray-300 truncate flex-1">{s.shot_type_ja}</span>
                            <span className="font-semibold ml-2 shrink-0" style={{ color: WIN }}>
                              {s.win_rate !== undefined ? `${(s.win_rate * 100).toFixed(0)}%` : '-'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div>
                    <p className="text-xs font-semibold mb-1.5" style={{ color: LINE }}>
                      {t('analysis.set_summary.risky_shots')}
                    </p>
                    {data.risky_shots.length === 0 ? (
                      <p className="text-xs text-gray-600">{t('analysis.no_data')}</p>
                    ) : (
                      <div className="space-y-1">
                        {data.risky_shots.map((s, i) => (
                          <div key={i} className="flex items-center justify-between text-xs">
                            <span className="text-gray-300 truncate flex-1">{s.shot_type_ja}</span>
                            <span className="font-semibold ml-2 shrink-0" style={{ color: LINE }}>
                              {s.loss_rate !== undefined ? `失${(s.loss_rate * 100).toFixed(0)}%` : '-'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </RoleGuard>
            </>
          )}

          {/* アクションボタン */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={onClose}
              className="flex-1 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
            >
              {t('analysis.set_summary.skip')}
            </button>
            <button
              onClick={onNextSet}
              className="flex-1 py-2 rounded text-sm font-medium flex items-center justify-center gap-1 text-white"
              style={{ backgroundColor: WIN }}
            >
              {t('analysis.set_summary.next_set')}
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
