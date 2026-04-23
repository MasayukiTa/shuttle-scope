// CoachSummaryStrip — 試合前コーチ向け圧縮サマリー (Spec §3.1 / §10)
// 5スロット固定。常時表示、折りたたみなし。
import { useTranslation } from 'react-i18next'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'

interface TacticalNote {
  note: string
  estimated_impact: string
  basis: string
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

function winColor(p: number, neutral: string): string {
  if (p >= 0.55) return WIN
  if (p <= 0.45) return LOSS
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
  const neutral = isLight ? '#334155' : '#e2e8f0'
  const subText = isLight ? '#64748b' : '#9ca3af'
  const bg = isLight ? 'bg-blue-50 border-blue-200' : 'bg-gray-900 border-gray-700'

  const winPct = Math.round(winProbability * 100)
  const confPct = Math.round(confidence * 100)
  const topResult = topOutcome(setDistribution)

  // 最大リスク: caution_flags > "リスクなし"
  const topRisk = cautionFlags[0] ?? null

  // 推奨アクション: tactical_notes[0]
  const firstNote = tacticalNotes[0]
  const topAction = firstNote
    ? (typeof firstNote === 'string' ? firstNote : firstNote.note)
    : null

  return (
    <div className={`rounded-lg border px-4 py-3 mb-4 ${bg}`}>
      <p className="text-[10px] font-semibold tracking-widest uppercase mb-2" style={{ color: subText }}>
        {t('prediction.coach_summary')}
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {/* 勝率 */}
        <div>
          <p className="text-2xl font-bold leading-none" style={{ color: winColor(winProbability, neutral) }}>
            {winPct}%
          </p>
          <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.win_probability')}</p>
          {recentForm && recentForm.sample > 0 && (
            <p className="text-[10px] mt-0.5 font-medium" style={{
              color: recentForm.trend === 'improving' ? WIN
                   : recentForm.trend === 'declining' ? LOSS
                   : subText,
            }}>
              {recentForm.trend === 'improving' ? t('prediction.recent_form_improving')
             : recentForm.trend === 'declining' ? t('prediction.recent_form_declining')
             : t('prediction.recent_form_stable')}
            </p>
          )}
        </div>

        {/* 信頼度 */}
        <div>
          <p className="text-lg font-bold leading-none" style={{ color: neutral }}>
            {confPct}% <span className="text-sm font-normal">{confidenceStars}</span>
          </p>
          <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.confidence')}</p>
          {sampleSize < 10 && (
            <p className="text-[10px]" style={{ color: LOSS }}>{t('auto.CoachSummaryStrip.k1')}</p>
          )}
        </div>

        {/* 最頻結果 */}
        <div>
          <p className="text-2xl font-bold leading-none" style={{ color: neutral }}>{topResult}</p>
          <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.most_likely')}</p>
        </div>

        {/* 最大リスク */}
        <div className="sm:col-span-1">
          {topRisk ? (
            <>
              <p className="text-xs font-medium leading-snug" style={{ color: LOSS }}>⚠ {topRisk}</p>
              <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.biggest_risk')}</p>
            </>
          ) : (
            <>
              <p className="text-xs font-medium" style={{ color: subText }}>—</p>
              <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.biggest_risk')}</p>
            </>
          )}
        </div>

        {/* 推奨アクション */}
        <div className="sm:col-span-1">
          {topAction ? (
            <>
              <p className="text-xs font-medium leading-snug" style={{ color: WIN }}>→ {topAction}</p>
              <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.top_action')}</p>
            </>
          ) : (
            <>
              <p className="text-xs font-medium" style={{ color: subText }}>—</p>
              <p className="text-[10px] mt-0.5" style={{ color: subText }}>{t('prediction.top_action')}</p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
