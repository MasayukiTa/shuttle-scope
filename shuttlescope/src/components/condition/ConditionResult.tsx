import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import { ConditionResult as ConditionResultType, _FactorKey } from '@/hooks/useConditions'

interface Props {
  result: ConditionResultType
  /** 信頼度表示用: 同一選手の過去履歴件数 */
  historyCount?: number
  isLight?: boolean
}

function labelColor(label: string): string {
  if (label === 'good') return 'text-[var(--ss-success)] bg-[var(--ss-success-tint)] border-[var(--ss-success-border)]'
  if (label === 'caution') return 'text-[var(--ss-warn)] bg-[var(--ss-warn-tint)] border-[var(--ss-warning-border)]'
  return 'text-[var(--ss-bad)] bg-[var(--ss-danger-tint)] border-[var(--ss-danger-border)]'
}

// Phase 2: 結果画面。role により表示項目を厳格に切替。
export function ConditionResult({ result, historyCount, isLight }: Props) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const panelCls = 'bg-[var(--ss-surface-1)] border-[var(--ss-border)]'
  const muted = 'text-[var(--ss-t2)]'

  // 信頼度バッジ（履歴件数ベース）
  const hc = historyCount ?? result.history_count ?? 0
  let confLabel: string
  let confColor: string
  if (hc < 7) {
    confLabel = t('condition.confidence.accumulating')
    confColor = 'border-[var(--ss-danger-border)] bg-[var(--ss-danger-tint)] text-[var(--ss-bad)]'
  } else if (hc < 28) {
    confLabel = t('condition.confidence.reference')
    confColor = 'border-[var(--ss-warning-border)] bg-[var(--ss-warn-tint)] text-[var(--ss-warn)]'
  } else {
    confLabel = t('condition.confidence.normal')
    confColor = 'border-[var(--ss-success-border)] bg-[var(--ss-success-tint)] text-[var(--ss-success)]'
  }

  const ccs = result.ccs ?? null
  const rangeLow = result.personal_range_low ?? null
  const rangeHigh = result.personal_range_high ?? null
  const factors = result.factors ?? []

  // 平常レンジバー計算（CCS を 0-100 仮定）
  const pctOf = (v: number | null) => (v == null ? null : Math.max(0, Math.min(100, v)))
  const ccsPct = pctOf(ccs)
  const lowPct = pctOf(rangeLow)
  const highPct = pctOf(rangeHigh)

  const showCoach = role === 'coach' || role === 'analyst' || role === 'admin'
  const showAnalyst = role === 'analyst' || role === 'admin'

  return (
    <div className="space-y-4">
      {/* CCS + ConfidenceBadge */}
      <section className={`rounded-ss-lg border p-4 shadow-card ${panelCls}`}>
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-semibold">{t('condition.result.ccs')}</div>
          <div className={`inline-flex items-center gap-2 px-2 py-1 rounded-ss-sm border text-xs ${confColor}`}>
            <span>{confLabel}</span>
            <span className="opacity-70">{t('condition.confidence.records', { n: hc })}</span>
          </div>
        </div>
        <div className="text-3xl font-bold ss-num text-[var(--ss-t1)]">
          {ccs != null ? ccs.toFixed(1) : '—'}
        </div>

        {/* 平常レンジバー */}
        {ccsPct != null && (
          <div className="mt-3">
            <div className={`text-xs mb-1 ${muted}`}>
              {t('condition.result.personal_range')}
              {lowPct != null && highPct != null ? `: ${rangeLow?.toFixed(1)} 〜 ${rangeHigh?.toFixed(1)}` : ''}
            </div>
            <div className="relative h-3 bg-[var(--ss-surface-2)] rounded-ss-sm overflow-hidden">
              {lowPct != null && highPct != null && (
                <div
                  className="absolute h-full bg-[var(--ss-brand-tint)]"
                  style={{ left: `${lowPct}%`, width: `${Math.max(0, highPct - lowPct)}%` }}
                />
              )}
              <div
                className="absolute top-0 bottom-0 w-1 bg-[var(--ss-brand)]"
                style={{ left: `calc(${ccsPct}% - 2px)` }}
              />
            </div>
            <div className={`text-[11px] mt-1 ${muted}`}>{t('condition.result.personal_range_note')}</div>
          </div>
        )}

        {result.delta_28ma != null && (
          <div className={`text-xs mt-2 ss-num ${muted}`}>
            {t('condition.result.delta_28ma')}: {result.delta_28ma >= 0 ? '+' : ''}{result.delta_28ma.toFixed(1)}
          </div>
        )}
      </section>

      {/* 因子別ラベル（全ロール） */}
      {factors.length > 0 && (
        <section className={`rounded-ss-lg border p-4 shadow-card ${panelCls}`}>
          <div className="text-sm font-semibold mb-3">{t('auto.ConditionResult.k1')}</div>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {factors.map((f) => (
              <div key={f.factor} className={`border rounded-ss-sm p-2 ${labelColor(f.label)}`}>
                <div className="text-[10px] font-mono opacity-80">{f.factor}</div>
                <div className="text-[11px] leading-tight mt-0.5">
                  {t(`condition.factor.${f.factor}` as unknown as string)}
                </div>
                <div className="text-sm font-semibold mt-1">
                  {t(`condition.result.label.${f.label}` as unknown as string)}
                </div>
                {showCoach && f.raw != null && (
                  <div className="text-[10px] opacity-70 mt-0.5">{t('auto.ConditionResult.raw', { v: f.raw.toFixed(2) })}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* player には肯定的コメントのみ */}
      {role === 'player' && (
        <div className={`text-sm ${muted} italic`}>{t('condition.result.positive_comment')}</div>
      )}

      {/* coach 以上: 生数値表示 */}
      {showCoach && (
        <section className={`rounded-ss-lg border p-4 shadow-card ${panelCls}`}>
          <div className="text-sm font-semibold mb-3">{t('auto.ConditionResult.k2')}</div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-xs">
            {(['f1', 'f2', 'f3', 'f4', 'f5'] as const).map((k) => (
              <div key={k} className="border border-[var(--ss-border)] rounded-ss-sm px-2 py-1">
                <div className={`text-[10px] ${muted}`}>{k.toUpperCase()}</div>
                <div className="font-mono ss-num">{result[k] != null ? (result[k] as number).toFixed(2) : '—'}</div>
              </div>
            ))}
            <div className="border border-[var(--ss-border)] rounded-ss-sm px-2 py-1">
              <div className={`text-[10px] ${muted}`}>{t('auto.ConditionResult.total')}</div>
              <div className="font-mono ss-num">{result.total_score != null ? result.total_score.toFixed(1) : '—'}</div>
            </div>
          </div>
          <div className="mt-2">
            <span
              className={
                'inline-flex items-center px-2 py-0.5 rounded-ss-sm text-xs border ' +
                (result.validity_flag
                  ? 'border-[var(--ss-success-border)] text-[var(--ss-success)] bg-[var(--ss-success-tint)]'
                  : 'border-[var(--ss-danger-border)] text-[var(--ss-bad)] bg-[var(--ss-danger-tint)]')
              }
            >
              {t('condition.result.validity')}: {result.validity_flag ? 'OK' : 'NG'}
            </span>
          </div>
        </section>
      )}

      {/* analyst: validity_score, flags, questionnaire_json */}
      {showAnalyst && (
        <section className={`rounded-ss-lg border p-4 shadow-card ${panelCls}`}>
          <div className="text-sm font-semibold mb-2">{t('auto.ConditionResult.k3')}</div>
          {result.validity_score != null && (
            <div className="text-xs mb-1">
              {t('auto.ConditionResult.validity_score_label')} <span className="font-mono ss-num">{result.validity_score.toFixed(3)}</span>
            </div>
          )}
          {result.flags_list && result.flags_list.length > 0 && (
            <div className="text-xs mb-1">
              <div className={muted}>{t('condition.result.flags')}:</div>
              <div className="flex flex-wrap gap-1 mt-1">
                {result.flags_list.map((f) => (
                  <span key={f} className="inline-flex px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-warn-tint)] border border-[var(--ss-warning-border)] text-[var(--ss-warn)] text-[10px]">
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.questionnaire_json && (
            <details className="text-xs mt-2">
              <summary className="cursor-pointer">{t('condition.result.responses_breakdown')}</summary>
              <pre className="mt-1 p-2 rounded-ss-sm overflow-x-auto text-[10px] bg-[var(--ss-surface-2)]">
                {JSON.stringify(result.questionnaire_json, null, 2)}
              </pre>
            </details>
          )}
        </section>
      )}
    </div>
  )
}
