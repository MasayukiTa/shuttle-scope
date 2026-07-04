// ペアシミュレーションパネル — Phase B
// アナリスト向け: パートナーランキング機能付き（コーチ・選手には非表示）
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { ConfidenceBadge } from '@/components/common/ConfidenceBadge'
import { SetDistributionBar } from '@/components/analysis/SetDistributionBar'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { WIN, LOSS } from '@/styles/colors'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useAuth } from '@/hooks/useAuth'
import { MIcon } from '@/components/common/MIcon'

interface PlayerSummary {
  id: number
  name: string
  team?: string
}

interface PairSimResponse {
  success: boolean
  data: {
    pair_name: string
    win_probability: number
    set_distribution: { '2-0': number; '2-1': number; '1-2': number; '0-2': number }
    pair_strengths: string[]
    pair_cautions: string[]
    confidence: number
    sample_size: number
  }
  meta: { sample_size: number; confidence: { level: string; stars: string; label: string } }
}

interface RankedPartner {
  rank: number
  partner_id: number
  partner_name: string
  partner_team: string | null
  win_probability: number
  sample_size: number
  confidence: number
  confidence_meta: { level: string; stars: string; label: string }
}

interface PairRankingResponse {
  success: boolean
  data: {
    anchor_player: { id: number; name: string }
    ranked_partners: RankedPartner[]
    tournament_level: string | null
  }
}

interface PairSimulationPanelProps {
  players: PlayerSummary[]
}

function winProbColor(p: number, isLight: boolean): string {
  const neutral = isLight ? '#1e293b' : '#e2e8f0'
  if (p >= 0.55) return WIN
  if (p <= 0.45) return LOSS
  return neutral
}

// ── アナリスト専用: パートナーランキング ──────────────────────────────────────

function PartnerRankingSection({
  players,
}: {
  players: PlayerSummary[]
}) {
  const { t } = useTranslation()

  const isLight = useIsLightMode()
  const neutral = isLight ? '#334155' : '#d1d5db'
  const subText = isLight ? '#64748b' : '#9ca3af'

  const [anchorId, setAnchorId] = useState<number | null>(null)
  const [level, setLevel] = useState('')
  const [run, setRun] = useState(false)

  const selectClass = `text-xs rounded-ss-md px-2 py-1.5 focus:outline-none bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] text-[var(--ss-t1)]`

  const { data: resp, isLoading } = useQuery({
    queryKey: ['pair-ranking', anchorId, level],
    queryFn: () =>
      apiGet<PairRankingResponse>('/prediction/pair_ranking', {
        anchor_player_id: anchorId!,
        ...(level ? { tournament_level: level } : {}),
      }),
    enabled: run && anchorId != null,
  })

  const anchor = resp?.data?.anchor_player
  const rawRanking = resp?.data?.ranked_partners ?? []

  // データあり（実績順）→ データなし（名前順）
  const withData = rawRanking.filter((r) => r.sample_size > 0)
    .sort((a, b) => b.win_probability - a.win_probability)
  const noData = rawRanking.filter((r) => r.sample_size === 0)
    .sort((a, b) => a.partner_name.localeCompare(b.partner_name, 'ja'))

  return (
    <div
      className="space-y-3 rounded-ss-lg p-4 mt-4 bg-[rgba(37,99,235,0.08)] border border-[var(--ss-brand)]"
    >
      {/* ヘッダー */}
      <div className="flex items-center gap-2">
        <MIcon name="military_tech" size={14} style={{ color: 'var(--ss-brand)' }} />
        <span className="text-xs font-semibold" style={{ color: 'var(--ss-brand)' }}>
          {t('pair.title', 'Analyst only — partner candidate ranking (record-based)')}
        </span>
      </div>

      <p className="text-[11px]" style={{ color: subText }}>
        {t('pair.desc', 'Win rates are computed from pair match records. Players with no data are listed at the end.')}
      </p>

      {/* 選手1 + 大会レベル */}
      <div className="flex gap-2 flex-wrap items-end">
        <div className="space-y-1 flex-1 min-w-[200px]">
          <p className="text-[10px]" style={{ color: subText }}>{t('auto.PairSimulationPanel.k1')}</p>
          <SearchableSelect
            options={players.map((p) => ({
              value: p.id,
              label: p.name,
              searchText: p.team ?? '',
              suffix: p.team ? `（${p.team}）` : undefined,
            }))}
            value={anchorId}
            onChange={(v) => { setAnchorId(v != null ? Number(v) : null); setRun(false) }}
            emptyLabel={t('common.select_player', 'Select player')}
            placeholder={t('auto.PairSimulationPanel.k7')}
          />
        </div>
        <div className="space-y-1">
          <p className="text-[10px]" style={{ color: subText }}>{t('auto.PairSimulationPanel.k2')}</p>
          <select
            value={level}
            onChange={(e) => { setLevel(e.target.value); setRun(false) }}
            className={selectClass}
          >
            <option value="">{t('auto.PairSimulationPanel.k3')}</option>
            {['IC', 'IS', 'SJL', '全日本', '国内'].map((lv) => (
              <option key={lv} value={lv}>{lv}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => setRun(true)}
          disabled={!anchorId}
          className="px-3 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {t('pair.compute_ranking', 'Compute ranking')}
        </button>
      </div>

      {/* ローディング */}
      {isLoading && (
        <p className="text-xs text-center py-3" style={{ color: subText }}>{t('auto.PairSimulationPanel.k4')}</p>
      )}

      {/* 結果一覧 */}
      {!isLoading && (withData.length > 0 || noData.length > 0) && (
        <div className="space-y-2">
          <p className="text-[11px] font-medium" style={{ color: subText }}>
            {t('pair.ranking_for', { name: anchor?.name, defaultValue: 'Pair record ranking for {{name}}' })}
          </p>

          {/* データあり */}
          <div className="space-y-1 max-h-72 overflow-y-auto pr-1">
            {withData.map((r, idx) => {
              const rank = idx + 1
              const pct = Math.round(r.win_probability * 100)
              return (
                <div
                  key={r.partner_id}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-ss-md bg-[var(--ss-surface-1)]"
                  style={{
                    border: rank <= 3
                      ? `1px solid ${rank === 1 ? WIN : 'var(--ss-brand)'}40`
                      : `1px solid transparent`,
                  }}
                >
                  <span
                    className="text-xs font-bold w-5 text-center shrink-0"
                    style={{ color: rank === 1 ? WIN : rank <= 3 ? 'var(--ss-brand)' : subText }}
                  >
                    {rank}
                  </span>
                  <span
                    className="flex-1 min-w-0 text-xs font-medium truncate"
                    style={{ color: neutral }}
                    title={r.partner_team ? `${r.partner_name} (${r.partner_team})` : r.partner_name}
                  >
                    {r.partner_name}
                    {r.partner_team && (
                      <span className="ml-1 opacity-50 font-normal">{t('common.paren', { v: r.partner_team, defaultValue: '({{v}})' })}</span>
                    )}
                  </span>
                  {/* xs: ConfidenceBadge と試合数を hide して名前領域を確保 */}
                  <span className="hidden sm:inline-flex"><ConfidenceBadge sampleSize={r.sample_size} /></span>
                  <span className="hidden sm:inline text-[10px] shrink-0 ss-num" style={{ color: subText }}>
                    {t('lineup.n_matches', { n: r.sample_size, defaultValue: '{{n}} matches' })}
                  </span>
                  <div className="flex items-center gap-1 shrink-0">
                    <div className="w-14 h-1.5 rounded-full overflow-hidden bg-[var(--ss-surface-2)]">
                      <div
                        className="h-full rounded-full transition-all duration-base ease-out"
                        style={{ width: `${pct}%`, background: pct >= 55 ? WIN : pct <= 45 ? LOSS : '#d97706' }}
                      />
                    </div>
                    <span
                      className="text-xs font-bold w-9 text-right shrink-0 ss-num"
                      style={{ color: pct >= 55 ? WIN : pct <= 45 ? LOSS : neutral }}
                    >
                      {pct}%
                    </span>
                  </div>
                </div>
              )
            })}
          </div>

          {/* データなし（折りたたみ区切り） */}
          {noData.length > 0 && (
            <details className="mt-1">
              <summary
                className="text-[11px] cursor-pointer select-none"
                style={{ color: subText }}
              >
                {t('pair.no_record_n', { count: noData.length, defaultValue: 'No pair record — {{count}} players (click to expand)' })}
              </summary>
              <div className="mt-1 space-y-1">
                {noData.map((r) => (
                  <div
                    key={r.partner_id}
                    className="flex items-center gap-2 px-3 py-1 rounded-ss-md bg-[var(--ss-surface-2)] border border-transparent"
                  >
                    <span className="text-[10px] w-5 text-center shrink-0" style={{ color: subText }}>—</span>
                    <span className="flex-1 text-xs truncate" style={{ color: subText }}>
                      {r.partner_name}
                      {r.partner_team && <span className="ml-1 opacity-50">{t('common.paren', { v: r.partner_team, defaultValue: '({{v}})' })}</span>}
                    </span>
                    <span className="text-[10px] shrink-0" style={{ color: subText }}>{t('auto.PairSimulationPanel.k5')}</span>
                  </div>
                ))}
              </div>
            </details>
          )}

          <p className="text-[10px]" style={{ color: subText }}>
            {t('pair.small_sample_note', '* Small samples (under 3 matches) have low statistical reliability.')}
          </p>
        </div>
      )}

      {!isLoading && run && withData.length === 0 && noData.length === 0 && (
        <p className="text-xs text-center py-3" style={{ color: subText }}>
          {t('pair.no_candidates', 'No candidate data')}
        </p>
      )}
    </div>
  )
}

// ── メインコンポーネント ──────────────────────────────────────────────────────

export function PairSimulationPanel({ players }: PairSimulationPanelProps) {
  const { t } = useTranslation()
  const { role } = useAuth()
  const isLight = useIsLightMode()
  const [pid1, setPid1] = useState<number | null>(null)
  const [pid2, setPid2] = useState<number | null>(null)
  const [level, setLevel] = useState('')
  const [run, setRun] = useState(false)

  const neutral = isLight ? '#334155' : '#d1d5db'
  const subText = isLight ? '#64748b' : '#9ca3af'

  const { data: resp, isLoading } = useQuery({
    queryKey: ['pair-simulation', pid1, pid2, level],
    queryFn: () =>
      apiGet<PairSimResponse>('/prediction/pair_simulation', {
        player_id_1: pid1!,
        player_id_2: pid2!,
        ...(level ? { tournament_level: level } : {}),
      }),
    enabled: run && pid1 != null && pid2 != null && pid1 !== pid2,
  })

  const selectClass = `text-xs rounded-ss-md px-2 py-1.5 focus:outline-none bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] text-[var(--ss-t1)]`

  const d = resp?.data

  return (
    <div className="space-y-4">
      {/* ── コーチ共通: ペア指定シミュレーション ── */}
      <div className="space-y-2">
        <div className="flex gap-2 flex-wrap">
          <div className="space-y-1 flex-1 min-w-[180px]">
            <p className="text-[10px]" style={{ color: subText }}>{t('prediction.pair_select_1')}</p>
            <SearchableSelect
              options={players.map((p) => ({
                value: p.id,
                label: p.name,
                searchText: p.team ?? '',
                suffix: p.team ? `（${p.team}）` : undefined,
              }))}
              value={pid1}
              onChange={(v) => { setPid1(v != null ? Number(v) : null); setRun(false) }}
              emptyLabel="— 選手1 —"
              placeholder={t('auto.PairSimulationPanel.k7')}
            />
          </div>
          <div className="space-y-1 flex-1 min-w-[180px]">
            <p className="text-[10px]" style={{ color: subText }}>{t('prediction.pair_select_2')}</p>
            <SearchableSelect
              options={players
                .filter((p) => p.id !== pid1)
                .map((p) => ({
                  value: p.id,
                  label: p.name,
                  searchText: p.team ?? '',
                  suffix: p.team ? `（${p.team}）` : undefined,
                }))}
              value={pid2}
              onChange={(v) => { setPid2(v != null ? Number(v) : null); setRun(false) }}
              emptyLabel="— 選手2 —"
              placeholder={t('auto.PairSimulationPanel.k7')}
            />
          </div>
        </div>
        <div className="flex gap-2 flex-wrap items-end">
          <div className="space-y-1">
            <p className="text-[10px]" style={{ color: subText }}>{t('auto.PairSimulationPanel.k6')}</p>
            <select value={level} onChange={(e) => { setLevel(e.target.value); setRun(false) }} className={selectClass}>
              <option value="">{t('auto.PairSimulationPanel.k3')}</option>
              {['IC', 'IS', 'SJL', '全日本', '国内'].map((lv) => (
                <option key={lv} value={lv}>{lv}</option>
              ))}
            </select>
          </div>
          <button
            onClick={() => setRun(true)}
            disabled={!pid1 || !pid2 || pid1 === pid2}
            className="px-3 py-1.5 rounded text-xs font-medium bg-gray-600 hover:bg-gray-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {t('prediction.run_simulation')}
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="text-[var(--ss-t3)] text-sm py-4 text-center">{t('prediction.loading')}</div>
      )}

      {d && (
        <div className="bg-[var(--ss-surface-2)] rounded-ss-lg p-4 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-semibold min-w-0 truncate max-w-full" style={{ color: neutral }} title={d.pair_name}>{d.pair_name}</span>
            <ConfidenceBadge sampleSize={d.sample_size} />
            <span className="text-xs ss-num" style={{ color: subText }}>{t('lineup.n_matches', { n: d.sample_size, defaultValue: '{{n}} matches' })}</span>
          </div>

          <div className="text-center">
            <p className="text-4xl font-bold ss-num" style={{ color: winProbColor(d.win_probability, isLight) }}>
              {Math.round(d.win_probability * 100)}%
            </p>
            <p className="text-xs mt-1" style={{ color: subText }}>{t('prediction.win_probability')}</p>
          </div>

          {d.sample_size > 0 && (
            <div>
              <p className="text-xs font-medium mb-2" style={{ color: subText }}>{t('prediction.set_distribution')}</p>
              <SetDistributionBar distribution={d.set_distribution} />
            </div>
          )}

          {d.pair_strengths.length > 0 && (
            <ul className="space-y-1">
              {d.pair_strengths.map((s, i) => (
                <li key={i} className="text-xs inline-flex items-center gap-1" style={{ color: WIN }}><MIcon name="check" size={12} />{s}</li>
              ))}
            </ul>
          )}
          {d.pair_cautions.length > 0 && (
            <ul className="space-y-1">
              {d.pair_cautions.map((c, i) => (
                <li key={i} className="text-xs inline-flex items-center gap-1" style={{ color: subText }}><MIcon name="warning" size={12} />{c}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* ── アナリスト/管理者向け: ベストパートナーランキング ── */}
      {(role === 'analyst' || role === 'admin') && (
        <PartnerRankingSection players={players} />
      )}
    </div>
  )
}
