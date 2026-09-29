/**
 * U3 解析モード — リアルタイム集計を表示する。
 *
 * 表示内容 (現状はストロークログから即計算できる軽量集計のみ):
 *   - 直近 5 ラリーの勝敗 (momentum)
 *   - 現セット内のショット種別カウント
 *   - サーブ権の遷移状況
 *
 * Track B (ConfidenceCalibrator) や Track C (SwingDetector / RTMPose) の
 * リアルタイム値も将来ここに統合する想定。
 */
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import type { StrokeInput } from '@/types'

interface AnalysisModePanelProps {
  scoreA: number
  scoreB: number
  setNum: number
  rallyNum: number
  recentStrokes: StrokeInput[]   // 当該ラリー内
  recentRallyResults?: Array<{ winner: 'player_a' | 'player_b' }>
}

export function AnalysisModePanel({
  scoreA, scoreB, setNum, rallyNum,
  recentStrokes, recentRallyResults = [],
}: AnalysisModePanelProps) {
  const { t } = useTranslation()
  const shotCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const s of recentStrokes) {
      c[s.shot_type] = (c[s.shot_type] ?? 0) + 1
    }
    return Object.entries(c).sort((a, b) => b[1] - a[1])
  }, [recentStrokes])

  const last5 = recentRallyResults.slice(-5)
  const aWins = last5.filter((r) => r.winner === 'player_a').length

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="flex items-center gap-2 px-3 py-2 text-sm font-medium border-b border-[var(--ss-border)] shrink-0 bg-[var(--ss-surface-2)] text-[var(--ss-t1)]">
        <MIcon name="analytics" size={18} />
        {t('annotator.ux.analysis_header')}
      </header>

      <div className="px-3 py-3 space-y-4 text-xs">
        <section>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ss-t3)] mb-1">{t('annotator.ux.analysis_now')}</div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-mono font-bold tabular-nums ss-num text-[var(--ss-t1)]">{scoreA}-{scoreB}</span>
            <span className="text-[var(--ss-t3)]">{t('auto.AnalysisModePanel.set_rally', { s: setNum, r: rallyNum })}</span>
          </div>
        </section>

        <section>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ss-t3)] mb-1">
            {t('annotator.ux.analysis_recent_5', { pct: last5.length ? Math.round((aWins / last5.length) * 100) : 0 })}
          </div>
          <div className="flex items-center gap-1">
            {last5.length === 0 && <span className="text-[var(--ss-t3)]">{t('annotator.ux.analysis_no_data')}</span>}
            {last5.map((r, i) => (
              <span
                key={i}
                className={
                  'inline-block w-6 h-6 rounded-ss-sm text-[10px] font-bold flex items-center justify-center ss-num ' +
                  (r.winner === 'player_a' ? 'bg-[var(--ss-good)] text-white' : 'bg-[var(--ss-bad)] text-white')
                }
                title={r.winner === 'player_a' ? 'A win' : 'B win'}
              >
                {r.winner === 'player_a' ? 'A' : 'B'}
              </span>
            ))}
          </div>
        </section>

        <section>
          <div className="text-[10px] uppercase tracking-wider text-[var(--ss-t3)] mb-1">
            {t('annotator.ux.analysis_shot_counts', { n: recentStrokes.length })}
          </div>
          {shotCounts.length === 0 ? (
            <div className="text-[var(--ss-t3)]">{t('annotator.ux.analysis_no_data')}</div>
          ) : (
            <ul className="space-y-1">
              {shotCounts.map(([shot, count]) => (
                <li key={shot} className="flex items-center justify-between border-b border-[var(--ss-border)] py-1">
                  <span className="text-[var(--ss-t2)]">{shot}</span>
                  <span className="font-mono tabular-nums ss-num text-[var(--ss-t1)]">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <p className="text-[10px] text-[var(--ss-t3)]">
          {t('annotator.ux.analysis_dashboard_hint')}
        </p>
      </div>
    </div>
  )
}
