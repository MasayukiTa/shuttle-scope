import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Heart, User, Trash2, FileDown } from 'lucide-react'
import { apiGet, apiDelete, API_BASE_URL } from '@/api/client'
import { Player } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { InBodyForm } from '@/components/condition/InBodyForm'
import { HooperRpeForm } from '@/components/condition/HooperRpeForm'
import { AuxiliaryForm } from '@/components/condition/AuxiliaryForm'
import { WeeklyQuestionnaire } from '@/components/condition/WeeklyQuestionnaire'
import { PreMatchQuestionnaire } from '@/components/condition/PreMatchQuestionnaire'
import { ConditionResult } from '@/components/condition/ConditionResult'
import { GrowthInsights } from '@/components/condition/GrowthInsights'
import { BestProfileCard } from '@/components/condition/BestProfileCard'
import { CorrelationScatter } from '@/components/condition/CorrelationScatter'
import { DiscrepancyAlertList } from '@/components/condition/DiscrepancyAlertList'
import { ConditionTrendChart } from '@/components/condition/ConditionTrendChart'
import { ConditionCorrelationHeatmap } from '@/components/condition/ConditionCorrelationHeatmap'
import { ConditionLagCorrelation } from '@/components/condition/ConditionLagCorrelation'
import { ConditionOutlierWeeks } from '@/components/condition/ConditionOutlierWeeks'
import { ConditionVolatilityRanking } from '@/components/condition/ConditionVolatilityRanking'
import { ConditionPCAScatter } from '@/components/condition/ConditionPCAScatter'
import { ConditionSeasonality } from '@/components/condition/ConditionSeasonality'
import { ConditionGenericScatter } from '@/components/condition/ConditionGenericScatter'
import { ConditionPostMatchChange } from '@/components/condition/ConditionPostMatchChange'
import { ConditionTagManager } from '@/components/condition/ConditionTagManager'
import { ConditionTagCompare } from '@/components/condition/ConditionTagCompare'
import { HistoryDetailModal } from '@/components/condition/HistoryDetailModal'
import {
  useCreateCondition,
  useConditions,
  ConditionPayload,
  ConditionResult as ConditionResultType,
} from '@/hooks/useConditions'

// Phase 2: 体調タブ
// 入力サブタブ内 3 モード: 質問票(週次) / 試合前チェック / 身体データ
// 履歴サブタブ: 簡易一覧 + 詳細モーダル（ConditionResult）
function todayYmd(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

type InputMode = 'weekly' | 'prematch' | 'body'

export function ConditionPage() {
  const { t } = useTranslation()
  const { role, playerId: authPlayerId } = useAuth()
  const { theme } = useTheme()
  const isLight = theme === 'light'

  const { data: playersResp } = useQuery({
    queryKey: ['players'],
    queryFn: () => apiGet<{ success: boolean; data: Player[] }>('/players'),
    enabled: role !== 'player',
  })
  const players: Player[] = playersResp?.data ?? []
  const sortedPlayers = useMemo(
    () =>
      [...players].sort((a, b) => {
        if (a.is_target && !b.is_target) return -1
        if (!a.is_target && b.is_target) return 1
        return a.name.localeCompare(b.name, 'ja')
      }),
    [players],
  )

  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(
    role === 'player' ? authPlayerId : null,
  )
  const effectivePlayerId = role === 'player' ? authPlayerId : selectedPlayerId

  const [subtab, setSubtab] = useState<'input' | 'history' | 'analytics'>('input')
  // player はデフォルトで週次質問票。coach/analyst も質問票を第一選択。
  const [mode, setMode] = useState<InputMode>('weekly')

  const [measuredAt, setMeasuredAt] = useState<string>(todayYmd())
  const [formState, setFormState] = useState<Partial<ConditionPayload>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [latestResult, setLatestResult] = useState<ConditionResultType | null>(null)
  const [detailRecord, setDetailRecord] = useState<Record<string, unknown> | null>(null)

  const patch = (p: Partial<ConditionPayload>) => {
    setFormState((prev) => ({ ...prev, ...p }))
  }

  const createMut = useCreateCondition()
  const { data: historyList = [] } = useConditions(effectivePlayerId ?? null, { limit: 60 })

  const validate = (): string | null => {
    const hooperKeys: (keyof ConditionPayload)[] = [
      'hooper_sleep', 'hooper_soreness', 'hooper_stress', 'hooper_fatigue',
    ]
    for (const k of hooperKeys) {
      const v = formState[k] as number | null | undefined
      if (v != null && (v < 1 || v > 7)) return t('condition.range_error_hooper')
    }
    const rpe = formState.session_rpe
    if (rpe != null && (rpe < 0 || rpe > 10)) return t('condition.range_error_rpe')
    return null
  }

  const handleBodySubmit = async () => {
    setErrorMsg(null)
    setSuccessMsg(null)
    if (!effectivePlayerId) {
      setErrorMsg(t('condition.save_failed'))
      return
    }
    const err = validate()
    if (err) { setErrorMsg(err); return }
    const payload: ConditionPayload = {
      ...formState,
      player_id: effectivePlayerId,
      measured_at: measuredAt,
      condition_type: 'weekly',
    }
    try {
      await createMut.mutateAsync(payload)
      setSuccessMsg(t('condition.saved'))
      setFormState({})
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMsg(`${t('condition.save_failed')}: ${msg}`)
    }
  }

  const handleQuestionnaireSubmitted = (result: ConditionResultType) => {
    setLatestResult(result)
    setSuccessMsg(t('condition.saved'))
  }

  const dlReport = (path: string, filename: string) => {
    const token = sessionStorage.getItem('shuttlescope_token')
    const fullUrl = API_BASE_URL + path.replace(/^\/api/, '')
    fetch(fullUrl, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      })
  }

  const cardBg = isLight ? 'bg-gray-50' : 'bg-gray-900'
  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const borderColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const textPrimary = isLight ? 'text-gray-900' : 'text-white'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'

  // player ロール: 身体データモードは非表示（質問票がメインフロー）
  const availableModes: InputMode[] =
    role === 'player' ? ['weekly', 'prematch'] : ['weekly', 'prematch', 'body']

  return (
    <div className={`flex flex-col h-full ${cardBg} ${textPrimary}`}>
      {/* ヘッダー */}
      <div className={`px-6 pt-6 pb-4 border-b ${borderColor} shrink-0`}>
        <div className="flex items-center gap-3 mb-4">
          <Heart className="text-pink-500" size={20} />
          <h1 className="text-xl font-semibold">{t('condition.title')}</h1>
        </div>

        {role === 'player' ? (
          <div className={`text-xs ${textMuted} italic`}>
            {t('condition.player_notice')}
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2 shrink-0">
              <User size={16} className={`${textMuted} shrink-0`} />
              <label className={`text-sm ${textMuted}`}>
                {t('condition.player_select')}：
              </label>
            </div>
            <SearchableSelect
              options={sortedPlayers.map((p) => ({
                value: p.id,
                label: p.name,
                searchText: p.team ?? '',
                prefix: p.is_target ? '★' : undefined,
                suffix: p.team ? `（${p.team}）` : undefined,
              }))}
              value={selectedPlayerId}
              onChange={(v) => setSelectedPlayerId(v != null ? Number(v) : null)}
              emptyLabel="— 選手を選択 —"
              placeholder={t('auto.ConditionPage.k2')}
              className="w-full sm:min-w-[280px] sm:max-w-md"
            />
          </div>
        )}
      </div>

      {/* ダウンロードボタン */}
      {effectivePlayerId && (
        <div className={`px-6 py-2 flex items-center justify-end gap-1.5 border-b ${borderColor}`}>
          <FileDown size={13} className={textMuted} />
          <button
            onClick={() => dlReport(`/api/reports/condition_pdf?player_id=${effectivePlayerId}`, `condition_${effectivePlayerId}.pdf`)}
            className={`text-xs px-2.5 py-1 rounded border transition-colors ${isLight ? 'border-gray-300 text-gray-600 hover:bg-gray-100' : 'border-gray-600 text-gray-300 hover:bg-gray-700'}`}
          >
            PDF
          </button>
          <button
            onClick={() => dlReport(`/api/reports/condition?player_id=${effectivePlayerId}`, `condition_${effectivePlayerId}.json`)}
            className={`text-xs px-2.5 py-1 rounded border transition-colors ${isLight ? 'border-gray-300 text-gray-600 hover:bg-gray-100' : 'border-gray-600 text-gray-300 hover:bg-gray-700'}`}
          >
            JSON
          </button>
        </div>
      )}

      {/* サブタブ */}
      <div className={`border-b ${borderColor} px-4`}>
        <div className="flex overflow-x-auto scrollbar-hide gap-1 py-2">
          {(['input', 'history', 'analytics'] as const).map((k) => (
            <button
              key={k}
              onClick={() => setSubtab(k)}
              className={`flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium whitespace-nowrap transition-colors ${
                subtab === k
                  ? 'bg-blue-600 text-white'
                  : isLight
                  ? 'text-gray-600 hover:bg-gray-100'
                  : 'text-gray-400 hover:bg-gray-800'
              }`}
            >
              {t(`condition.subtab_${k}`)}
            </button>
          ))}
        </div>
      </div>

      {/* 本体 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0 px-6 py-4">
        {!effectivePlayerId ? (
          <div className={`${textMuted} text-sm`}>{t('auto.ConditionPage.k1')}</div>
        ) : subtab === 'history' ? (
          <HistoryView
            list={historyList as unknown as Array<Record<string, unknown>>}
            isLight={isLight}
            canDelete={role !== 'player'}
            onSelect={(r) => {
              // 下位互換のため latestResult も更新しつつ、詳細モーダルを開く
              setLatestResult(r as unknown as ConditionResultType)
              setDetailRecord(r)
            }}
          />
        ) : subtab === 'analytics' ? (
          <div className="space-y-4">
            {/* 全ロール: 伸びしろインサイト（全幅リスト） */}
            <GrowthInsights playerId={effectivePlayerId} isLight={isLight} />

            {/* 全ロール: ベストプロフィール（全幅） */}
            <BestProfileCard playerId={effectivePlayerId} isLight={isLight} />

            {/* 全ロール: 時系列トレンド（全幅） */}
            <ConditionTrendChart playerId={effectivePlayerId} isLight={isLight} />

            {/* 追加解析: 全ロール共通 */}
            <>
              {/* 全幅: ヒートマップ（幅が必要） */}
              <ConditionCorrelationHeatmap playerId={effectivePlayerId} isLight={isLight} />

              {/* 2カラム: ラグ相関 + 季節性 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                <ConditionLagCorrelation playerId={effectivePlayerId} isLight={isLight} />
                <ConditionSeasonality playerId={effectivePlayerId} isLight={isLight} />
              </div>

              {/* 2カラム: 変動ランキング + 散布図 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                <ConditionVolatilityRanking playerId={effectivePlayerId} isLight={isLight} />
                <ConditionGenericScatter playerId={effectivePlayerId} isLight={isLight} />
              </div>

              {/* 2カラム: PCA + 試合前後変化 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                <ConditionPCAScatter playerId={effectivePlayerId} isLight={isLight} />
                <ConditionPostMatchChange playerId={effectivePlayerId} isLight={isLight} />
              </div>

              {/* 2カラム: 外れ週検出 + CorrelationScatter */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                <ConditionOutlierWeeks playerId={effectivePlayerId} isLight={isLight} />
                <CorrelationScatter playerId={effectivePlayerId} isLight={isLight} />
              </div>

              {/* 全幅: タグ管理・比較 */}
              <ConditionTagManager playerId={effectivePlayerId} isLight={isLight} />
              <ConditionTagCompare playerId={effectivePlayerId} isLight={isLight} />

              {/* 全幅: 乖離アラート */}
              <DiscrepancyAlertList playerId={effectivePlayerId} isLight={isLight} />
            </>

          </div>
        ) : (
          <div className="space-y-5 max-w-4xl">
            {/* モード切替 */}
            <div className="flex overflow-x-auto scrollbar-hide gap-1">
              {availableModes.map((m) => (
                <button
                  key={m}
                  onClick={() => { setMode(m); setLatestResult(null); setSuccessMsg(null); setErrorMsg(null) }}
                  className={`flex-shrink-0 px-3 py-1.5 rounded text-xs font-medium whitespace-nowrap transition-colors ${
                    mode === m
                      ? 'bg-pink-600 text-white'
                      : isLight
                      ? 'text-gray-700 hover:bg-gray-100 border border-gray-200'
                      : 'text-gray-300 hover:bg-gray-800 border border-gray-700'
                  }`}
                >
                  {t(`condition.mode.${m}`)}
                </button>
              ))}
            </div>

            {/* 測定日 */}
            <div className="flex items-center gap-3">
              <label className={`text-xs ${textMuted} shrink-0`}>
                {t('condition.measured_at')}：
              </label>
              <input
                type="date"
                className={
                  isLight
                    ? 'border border-gray-300 bg-white text-gray-900 rounded px-2 py-1.5 text-sm'
                    : 'border border-gray-600 bg-gray-800 text-white rounded px-2 py-1.5 text-sm'
                }
                value={measuredAt}
                onChange={(e) => setMeasuredAt(e.target.value)}
              />
            </div>

            {/* 結果表示（質問票送信直後） */}
            {latestResult && (
              <ConditionResult
                result={latestResult}
                historyCount={historyList.length}
                isLight={isLight}
              />
            )}

            {mode === 'weekly' && (
              <WeeklyQuestionnaire
                playerId={effectivePlayerId}
                measuredAt={measuredAt}
                isLight={isLight}
                onSubmitted={handleQuestionnaireSubmitted}
              />
            )}

            {mode === 'prematch' && (
              <PreMatchQuestionnaire
                playerId={effectivePlayerId}
                measuredAt={measuredAt}
                isLight={isLight}
                onSubmitted={handleQuestionnaireSubmitted}
              />
            )}

            {mode === 'body' && role !== 'player' && (
              <>
                <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
                  <h2 className="text-sm font-semibold mb-3">{t('condition.section_inbody')}</h2>
                  <InBodyForm value={formState} onChange={patch} isLight={isLight} />
                </section>

                <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
                  <h2 className="text-sm font-semibold mb-3">{t('condition.section_hooper_rpe')}</h2>
                  <HooperRpeForm value={formState} onChange={patch} isLight={isLight} />
                </section>

                <section className={`rounded-lg border ${borderColor} ${panelBg} p-4`}>
                  <h2 className="text-sm font-semibold mb-3">{t('condition.section_auxiliary')}</h2>
                  <AuxiliaryForm value={formState} onChange={patch} isLight={isLight} />
                </section>

                {errorMsg && (
                  <div className="text-sm text-red-500 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
                    {errorMsg}
                  </div>
                )}
                {successMsg && (
                  <div className="text-sm text-green-500 bg-green-500/10 border border-green-500/30 rounded px-3 py-2">
                    {successMsg}
                  </div>
                )}

                <div className="flex justify-end">
                  <button
                    onClick={handleBodySubmit}
                    disabled={createMut.isPending}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded text-sm font-medium"
                  >
                    {createMut.isPending ? '...' : t('condition.save')}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {detailRecord && (
        <HistoryDetailModal
          record={detailRecord}
          isLight={isLight}
          onClose={() => setDetailRecord(null)}
        />
      )}
    </div>
  )
}

// 履歴タブ: フィルタ + 指標サマリー + 行クリックで詳細、coach/analyst は削除可
type HistoryFilter = 'all' | 'weekly' | 'pre_match' | 'body'
interface HistoryRow {
  id?: number
  measured_at?: string
  condition_type?: string
  ccs?: number | null
  f1?: number | null
  f2?: number | null
  f3?: number | null
  f4?: number | null
  f5?: number | null
  hooper_index?: number | null
  session_rpe?: number | null
  sleep_hours?: number | null
  weight_kg?: number | null
}
interface HistoryViewProps {
  list: Array<Record<string, unknown>>
  isLight: boolean
  canDelete: boolean
  onSelect: (r: Record<string, unknown>) => void
}

function HistoryView({ list, isLight, canDelete, onSelect }: HistoryViewProps) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<HistoryFilter>('all')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const muted = isLight ? 'text-gray-500' : 'text-gray-400'
  const panelCls = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'
  const filterBtnBase = 'px-3 py-1 rounded text-xs font-medium transition-colors'
  const filterBtnOff = isLight ? 'text-gray-700 hover:bg-gray-100 border border-gray-200' : 'text-gray-300 hover:bg-gray-800 border border-gray-700'

  const rows: HistoryRow[] = (list as unknown as HistoryRow[]) ?? []
  const filtered = rows
    .filter((r) => {
      if (filter === 'all') return true
      if (filter === 'body') {
        // 身体データ主体: F1-F5/ccs 無しかつ weight/muscle 等ある
        return r.ccs == null && (r.weight_kg != null || r.session_rpe != null || r.hooper_index != null)
      }
      return r.condition_type === filter
    })
    .sort((a, b) => (b.measured_at ?? '').localeCompare(a.measured_at ?? ''))

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('condition.history.delete_confirm') as string)) return
    setDeletingId(id)
    try {
      await apiDelete(`/conditions/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() })
      qc.invalidateQueries({ queryKey: ['conditions'] })
    } finally {
      setDeletingId(null)
    }
  }

  const filterOpts: Array<{ key: HistoryFilter; label: string }> = [
    { key: 'all', label: t('condition.history.filter_all') },
    { key: 'weekly', label: t('condition.history.filter_weekly') },
    { key: 'pre_match', label: t('condition.history.filter_prematch') },
    { key: 'body', label: t('condition.history.filter_body') },
  ]

  if (!rows || rows.length === 0) {
    return <div className={`${muted} text-sm`}>{t('condition.history_placeholder')}</div>
  }

  const typeLabel = (ctype?: string): string => {
    if (ctype === 'weekly') return t('condition.history.type_weekly')
    if (ctype === 'pre_match') return t('condition.history.type_pre_match')
    return t('condition.history.type_body')
  }

  const fmt = (v: number | null | undefined, digits = 1): string =>
    v == null ? '—' : Number(v).toFixed(digits)

  return (
    <div className="space-y-3 max-w-4xl">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {filterOpts.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setFilter(opt.key)}
              className={`${filterBtnBase} ${filter === opt.key ? 'bg-blue-600 text-white' : filterBtnOff}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <span className={`text-xs ${muted}`}>
          {t('condition.history.count', { n: filtered.length })}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className={`${muted} text-sm`}>{t('condition.history.no_match')}</div>
      ) : (
        <div className="space-y-2">
          {filtered.map((r, idx) => (
            <div
              key={r.id ?? idx}
              className={`border rounded-lg ${panelCls} hover:opacity-90 transition-opacity`}
            >
              <button
                onClick={() => onSelect(r as unknown as Record<string, unknown>)}
                className="w-full text-left px-3 py-2"
              >
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium num-cell">{r.measured_at ?? ''}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border ${isLight ? 'border-gray-300 text-gray-600' : 'border-gray-600 text-gray-300'}`}>
                      {typeLabel(r.condition_type)}
                    </span>
                  </div>
                  {/* xs: 2 列 grid (5 指標は 3 行で安定)、sm+: 横並び flex-wrap で 1-2 行に */}
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:flex sm:flex-wrap sm:items-center sm:gap-x-3 sm:gap-y-1 text-xs num-cell">
                    {r.ccs != null && (
                      <span>{t('condition.history.ccs')}: <span className="text-blue-500">{fmt(r.ccs)}</span></span>
                    )}
                    {r.hooper_index != null && (
                      <span>{t('condition.history.hooper')}: {fmt(r.hooper_index, 0)}</span>
                    )}
                    {r.session_rpe != null && (
                      <span>{t('condition.history.rpe')}: {fmt(r.session_rpe, 0)}</span>
                    )}
                    {r.sleep_hours != null && (
                      <span>{t('condition.history.sleep_h')}: {fmt(r.sleep_hours)}</span>
                    )}
                    {r.weight_kg != null && (
                      <span>{t('condition.history.weight')}: {fmt(r.weight_kg)}</span>
                    )}
                  </div>
                </div>
                {(r.f1 != null || r.f2 != null || r.f3 != null || r.f4 != null || r.f5 != null) && (
                  <div className={`mt-1 grid grid-cols-3 gap-x-3 gap-y-1 sm:flex sm:gap-3 text-[11px] num-cell ${muted}`}>
                    {(['f1', 'f2', 'f3', 'f4', 'f5'] as const).map((k) => {
                      const v = r[k] as number | null | undefined
                      return (
                        <span key={k}>
                          {k.toUpperCase()}: <span className={isLight ? 'text-gray-800' : 'text-gray-200'}>{fmt(v)}</span>
                        </span>
                      )
                    })}
                  </div>
                )}
              </button>
              {canDelete && r.id != null && (
                <div className="px-3 pb-2 flex justify-end">
                  <button
                    onClick={() => handleDelete(r.id!)}
                    disabled={deletingId === r.id}
                    className="flex items-center gap-1 text-[11px] text-red-500 hover:text-red-400 disabled:opacity-50"
                  >
                    <Trash2 size={12} />
                    {t('condition.history.delete')}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
