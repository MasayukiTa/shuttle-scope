import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import {
  ConditionResult as ConditionResultType,
  BackendFactorLabel,
  FactorField,
} from '@/hooks/useConditions'

interface Props {
  result: ConditionResultType
  /** 信頼度表示用: 同一選手の過去履歴件数 */
  historyCount?: number
  isLight?: boolean
}

// backend の CCS = 200 - total (total 40..200) なので 0..160。平常レンジバーの軸に使う。
const CCS_MAX = 160

const FACTOR_FIELDS: readonly FactorField[] = [
  'f1_physical',
  'f2_stress',
  'f3_mood',
  'f4_motivation',
  'f5_sleep_life',
]

// backend ラベル → 表示ラベル(i18n condition.result.label.*)。
// insufficient_data などは null (= 行を出さない。「良好」と偽らない)。
function displayLabel(l: BackendFactorLabel | string | undefined): 'good' | 'caution' | 'concern' | null {
  if (l === 'good') return 'good'
  if (l === 'caution_mild') return 'caution'
  if (l === 'caution') return 'concern'
  return null
}

// 有限な数だけを通す。null / undefined / NaN / 文字列は null (0 にしない)。
function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

// backend は validity_flags_json / questionnaire_json を JSON 文字列で返す。
function parseJson<T>(v: unknown): T | null {
  if (v == null) return null
  if (typeof v !== 'string') return v as T
  try {
    return JSON.parse(v) as T
  } catch {
    return null
  }
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
  const hc = num(historyCount) ?? num(result.history_count) ?? 0
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

  // backend の実キー: ccs_score / personal_range{low,high} / factor_labels / f1_physical…
  // (Tier 2 なので coach/analyst には来ない。無い・null・NaN は「—」で、0 にはしない)
  const ccs = num(result.ccs_score)
  const rangeLow = num(result.personal_range?.low)
  const rangeHigh = num(result.personal_range?.high)
  const deltaRaw = num(result.delta_28ma)
  const factors = FACTOR_FIELDS.flatMap((field) => {
    const label = displayLabel(result.factor_labels?.[field])
    return label ? [{ field, label, raw: num(result[field]) }] : []
  })
  // delta_28ma / 平常レンジの基準は「直近28回の記録」(28日間ではない)。
  // 実際に平均した件数 n_28 が 28 未満ならその件数を表示する。件数 0 は値自体が null。
  const n28 = typeof result.n_28 === 'number' && result.n_28 > 0 ? result.n_28 : null
  // backend calc_validity: 'ok' | 'caution' | 'unreliable' (真偽値ではない)
  const validity =
    result.validity_flag === 'ok' || result.validity_flag === 'caution' || result.validity_flag === 'unreliable'
      ? result.validity_flag
      : null
  const flagsList = parseJson<string[]>(result.validity_flags_json)
  const responses = parseJson<Record<string, number>>(result.questionnaire_json)

  // 平常レンジバー計算（CCS は 0..160）
  const pctOf = (v: number | null) => (v == null ? null : Math.max(0, Math.min(100, (v / CCS_MAX) * 100)))
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
            <div className={`text-[11px] mt-1 ${muted}`}>
              {n28 != null && n28 < 28
                ? t('condition.result.personal_range_note_n', { n: n28 })
                : t('condition.result.personal_range_note')}
            </div>
          </div>
        )}

        {deltaRaw != null && (
          <div className={`text-xs mt-2 ss-num ${muted}`}>
            {n28 != null && n28 < 28
              ? t('condition.result.delta_28ma_n', { n: n28 })
              : t('condition.result.delta_28ma')}: {deltaRaw >= 0 ? '+' : ''}{deltaRaw.toFixed(1)}
          </div>
        )}
      </section>

      {/* 因子別ラベル（全ロール） */}
      {factors.length > 0 && (
        <section className={`rounded-ss-lg border p-4 shadow-card ${panelCls}`}>
          <div className="text-sm font-semibold mb-3">{t('auto.ConditionResult.k1')}</div>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
            {factors.map((f) => (
              <div key={f.field} className={`border rounded-ss-sm p-2 ${labelColor(f.label)}`}>
                <div className="text-[10px] font-mono opacity-80">{f.field.slice(0, 2).toUpperCase()}</div>
                <div className="text-[11px] leading-tight mt-0.5">
                  {t(`condition.result.factor_name.${f.field}` as unknown as string)}
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
            {FACTOR_FIELDS.map((k) => {
              const v = num(result[k])
              return (
                <div key={k} className="border border-[var(--ss-border)] rounded-ss-sm px-2 py-1">
                  <div className={`text-[10px] ${muted}`}>{k.slice(0, 2).toUpperCase()}</div>
                  <div className="font-mono ss-num">{v != null ? v.toFixed(2) : '—'}</div>
                </div>
              )
            })}
            <div className="border border-[var(--ss-border)] rounded-ss-sm px-2 py-1">
              <div className={`text-[10px] ${muted}`}>{t('auto.ConditionResult.total')}</div>
              <div className="font-mono ss-num">{num(result.total_score) != null ? (result.total_score as number).toFixed(1) : '—'}</div>
            </div>
          </div>
          <div className="mt-2">
            <span
              className={
                'inline-flex items-center px-2 py-0.5 rounded-ss-sm text-xs border ' +
                (validity === 'ok'
                  ? 'border-[var(--ss-success-border)] text-[var(--ss-success)] bg-[var(--ss-success-tint)]'
                  : validity === 'caution'
                    ? 'border-[var(--ss-warning-border)] text-[var(--ss-warn)] bg-[var(--ss-warn-tint)]'
                    : validity === 'unreliable'
                      ? 'border-[var(--ss-danger-border)] text-[var(--ss-bad)] bg-[var(--ss-danger-tint)]'
                      : 'border-[var(--ss-border)] text-[var(--ss-t2)]')
              }
            >
              {t('condition.result.validity')}: {validity ? t(`condition.result.validity_level.${validity}` as unknown as string) : '—'}
            </span>
          </div>
        </section>
      )}

      {/* analyst: validity_score, flags, questionnaire_json */}
      {showAnalyst && (
        <section className={`rounded-ss-lg border p-4 shadow-card ${panelCls}`}>
          <div className="text-sm font-semibold mb-2">{t('auto.ConditionResult.k3')}</div>
          {num(result.validity_score) != null && (
            <div className="text-xs mb-1">
              {t('auto.ConditionResult.validity_score_label')} <span className="font-mono ss-num">{(result.validity_score as number).toFixed(3)}</span>
            </div>
          )}
          {Array.isArray(flagsList) && flagsList.length > 0 && (
            <div className="text-xs mb-1">
              <div className={muted}>{t('condition.result.flags')}:</div>
              <div className="flex flex-wrap gap-1 mt-1">
                {flagsList.map((f) => (
                  <span key={f} className="inline-flex px-1.5 py-0.5 rounded-ss-sm bg-[var(--ss-warn-tint)] border border-[var(--ss-warning-border)] text-[var(--ss-warn)] text-[10px]">
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}
          {responses && (
            <details className="text-xs mt-2">
              <summary className="cursor-pointer">{t('condition.result.responses_breakdown')}</summary>
              <ul
                className="mt-1 p-2 rounded-ss-sm text-[11px] bg-[var(--ss-surface-2)] space-y-0.5"
                data-testid="condition-responses"
              >
                {Object.entries(responses).map(([qid, val]) => (
                  <li key={qid} className="flex justify-between gap-3">
                    <span>{t(`condition.q.${qid}`, qid)}</span>
                    <span className="ss-num">{val}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
    </div>
  )
}
