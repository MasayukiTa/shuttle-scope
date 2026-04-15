import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Heart, User } from 'lucide-react'
import { apiGet } from '@/api/client'
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
          <div className="flex items-center gap-3">
            <User size={16} className={`${textMuted} shrink-0`} />
            <label className={`text-sm ${textMuted} shrink-0`}>
              {t('condition.player_select')}：
            </label>
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
              placeholder="選手名で検索..."
              className="min-w-[280px]"
            />
          </div>
        )}
      </div>

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
          <div className={`${textMuted} text-sm`}>選手を選択してください</div>
        ) : subtab === 'history' ? (
          <HistoryView
            list={historyList}
            isLight={isLight}
            onSelect={(r) => setLatestResult(r as unknown as ConditionResultType)}
          />
        ) : subtab === 'analytics' ? (
          <div className="space-y-4 max-w-5xl">
            {/* 全ロール: 伸びしろインサイトを最上段 */}
            <GrowthInsights playerId={effectivePlayerId} isLight={isLight} />

            {/* coach/analyst: 追加解析 */}
            {role !== 'player' && (
              <>
                <BestProfileCard playerId={effectivePlayerId} isLight={isLight} />
                <CorrelationScatter playerId={effectivePlayerId} isLight={isLight} />
                <DiscrepancyAlertList playerId={effectivePlayerId} isLight={isLight} />
              </>
            )}

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
    </div>
  )
}

// 履歴タブ: 時系列の簡易表示。詳細はモーダル代わりに onSelect で上位に渡して表示。
interface HistoryViewProps {
  list: Array<Record<string, unknown>>
  isLight: boolean
  onSelect: (r: Record<string, unknown>) => void
}

function HistoryView({ list, isLight, onSelect }: HistoryViewProps) {
  const { t } = useTranslation()
  const muted = isLight ? 'text-gray-500' : 'text-gray-400'
  if (!list || list.length === 0) {
    return <div className={`${muted} text-sm`}>{t('condition.history_placeholder')}</div>
  }
  const panelCls = isLight ? 'bg-white border-gray-200' : 'bg-gray-800 border-gray-700'
  return (
    <div className="space-y-2 max-w-3xl">
      {list.map((r, idx) => {
        const ccs = (r as { ccs?: number | null }).ccs ?? null
        const date = (r as { measured_at?: string }).measured_at ?? ''
        const ctype = (r as { condition_type?: string }).condition_type ?? ''
        return (
          <button
            key={(r as { id?: number }).id ?? idx}
            onClick={() => onSelect(r)}
            className={`w-full text-left border rounded-lg px-3 py-2 ${panelCls} hover:opacity-80 transition-opacity`}
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">{date}</div>
              <div className="text-xs">
                <span className={`mr-2 ${muted}`}>{ctype}</span>
                <span className="font-mono">CCS: {ccs != null ? (ccs as number).toFixed(1) : '—'}</span>
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}
