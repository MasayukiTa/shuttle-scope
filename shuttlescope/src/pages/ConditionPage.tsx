import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiPost, apiDelete, API_BASE_URL } from '@/api/client'
import { Player } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { SearchableSelect } from '@/components/common/SearchableSelect'
import { AdviceStrip } from '@/components/common/AdviceStrip'
import { ConditionGlossary } from '@/components/condition/ConditionGlossary'
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
import { useAutoTutorial } from '@/components/tutorial/useTutorial'
import {
  useCreateCondition,
  useConditions,
  ConditionPayload,
  ConditionResult as ConditionResultType,
} from '@/hooks/useConditions'
import { MIcon } from '@/components/common/MIcon'

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

/**
 * player 専用: 体組成データ (Tier 3) を analyst / coach に開示するかの toggle。
 * UserConsent (consent_type = body_disclose_to_analyst / body_disclose_to_coach)
 * に書き込み。 default OFF。
 */
function BodyDataConsentToggles() {
  const { t } = useTranslation()
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const queryClient = useQueryClient()
  // 体組成データ開示トグル初回表示時にチュートリアルを自動起動
  useAutoTutorial('body_disclosure_toggle')

  const { data, isLoading } = useQuery<{
    data?: {
      consents?: Array<{ consent_type: string; consent_given: boolean }>
      current_versions?: { privacy_policy?: string; terms?: string }
    }
  }>({
    queryKey: ['my-consents'],
    queryFn: () => apiGet('/auth/consents'),
    staleTime: 30_000,
  })
  const consents = data?.data?.consents ?? []
  const vPrivacy = data?.data?.current_versions?.privacy_policy ?? ''
  const vTerms = data?.data?.current_versions?.terms ?? ''
  const analystOn = consents.some((c) => c.consent_type === 'body_disclose_to_analyst' && c.consent_given)
  const coachOn = consents.some((c) => c.consent_type === 'body_disclose_to_coach' && c.consent_given)

  const submit = async (consent_type: string, consent_given: boolean) => {
    // 既存の他 type の同意も同じバージョンで再送する必要があるため、現在の dict を構成
    const body = {
      privacy_policy_version: vPrivacy,
      terms_version: vTerms,
      consents: [{ consent_type, consent_given }],
    }
    try {
      await apiPost('/auth/consents', body)
      queryClient.invalidateQueries({ queryKey: ['my-consents'] })
    } catch (e) {
      // backend が version mismatch (409) 等を返す場合はユーザに知らせる
       
      alert(`${t('condition.consent_update_failed', 'Failed to update consent')}: ${String(e).slice(0, 200)}`)
    }
  }

  return (
    <div
      data-tutorial="condition.disclosureToggle"
      className={`rounded-ss-lg border p-3 text-xs ${
        'bg-[var(--ss-brand-tint)] border-[var(--ss-border)] text-[var(--ss-t1)]'
      }`}
    >
      <div className="font-semibold mb-1.5">{t('condition.body_disclose_title', 'Body composition data (weight / body fat / muscle mass etc.) disclosure')}</div>
      <div className="opacity-80 mb-2 leading-relaxed">
        {t('condition.body_disclose_help', 'By default only you and the admin (developer) can view this. Toggle the switches below to share with analyst / coach. You can withdraw at any time.')}
      </div>
      {isLoading ? (
        <div className="opacity-60">{t('common.loading', 'Loading...')}</div>
      ) : (
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={analystOn}
              onChange={(e) => submit('body_disclose_to_analyst', e.target.checked)}
            />
            <span>{t('condition.body_disclose_to_analyst', 'Disclose to analyst')}</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={coachOn}
              onChange={(e) => submit('body_disclose_to_coach', e.target.checked)}
            />
            <span>{t('condition.body_disclose_to_coach', 'Disclose to coach (default OFF)')}</span>
          </label>
        </div>
      )}
    </div>
  )
}

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
  const players: Player[] = useMemo(() => playersResp?.data ?? [], [playersResp?.data])
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
  const [glossaryOpen, setGlossaryOpen] = useState(false)

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
    // 入力は常にログインユーザ自身 (authPlayerId)。代理入力は不可。
    if (!authPlayerId) {
      setErrorMsg(t('condition.player_only_input', 'Only accounts linked to a player record can submit'))
      return
    }
    const err = validate()
    if (err) { setErrorMsg(err); return }
    const payload: ConditionPayload = {
      ...formState,
      player_id: authPlayerId,
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

  const cardBg = 'bg-[var(--ss-bg-app)]'
  const panelBg = 'bg-[var(--ss-surface-1)]'
  const borderColor = 'border-[var(--ss-border)]'
  const textPrimary = 'text-[var(--ss-t1)]'
  const textMuted = 'text-[var(--ss-t3)]'

  // player ロール: 身体データモードは非表示（質問票がメインフロー）
  const availableModes: InputMode[] =
    role === 'player' ? ['weekly', 'prematch'] : ['weekly', 'prematch', 'body']

  return (
    <div className={`flex flex-col h-full ${cardBg} ${textPrimary}`}>
      {/* ヘッダー */}
      <div className={`px-6 pt-6 pb-4 border-b ${borderColor} shrink-0`}>
        <div className="flex items-center gap-3 mb-4">
          <MIcon name="favorite" className="text-[var(--ss-brand)]" size={20} />
          <h1 className="text-xl font-semibold">{t('condition.title')}</h1>
          <button
            type="button"
            onClick={() => setGlossaryOpen(true)}
            title={t('condition.glossary_tooltip', 'Definitions for CCS / F1–F5 / Hooper Sleep / RPE etc.')}
            className={`ml-auto inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-ss-md border ${'bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]'}`}
          >
            <span className="inline-flex items-center justify-center w-4 h-4 rounded-full border" style={{ borderColor: 'var(--ss-border-strong)' }}>?</span>
            {t('condition.glossary_btn', 'Glossary')}
          </button>
        </div>

        {role === 'player' ? (
          <div className="space-y-3">
            <div className={`text-xs ${textMuted} italic`}>
              {t('condition.player_notice')}
            </div>
            <BodyDataConsentToggles />
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
            {/* Round 258 #3: 同意書 第5条遵守の挙動説明 (coach/analyst には
                生スコア・体組成・医療記述は表示されない／自分自身の記録は入力可) */}
            {(role === 'coach' || role === 'analyst') && (
              <div
                className={`w-full text-xs px-3 py-2 rounded-ss-md border ${
                  'text-[var(--ss-warn)]'
                }`}
                style={isLight ? { backgroundColor: 'rgba(178,106,0,0.08)', borderColor: 'rgba(178,106,0,0.3)' } : undefined}
              >
                {t('condition.summary_only_notice')}
              </div>
            )}
            <div className="flex items-center gap-2 shrink-0">
              <MIcon name="person" size={16} className={`${textMuted} shrink-0`} />
              <label className={`text-sm ${textMuted}`}>
                {t('auto.ConditionPage.k4')}
              </label>
            </div>
            <SearchableSelect
              options={sortedPlayers.map((p) => ({
                value: p.id,
                label: p.name,
                searchText: p.team ?? '',
                prefix: p.is_target ? 'star' : undefined,
                prefixIsIcon: !!p.is_target,
                suffix: p.team ? `（${p.team}）` : undefined,
              }))}
              value={selectedPlayerId}
              onChange={(v) => setSelectedPlayerId(v != null ? Number(v) : null)}
              emptyLabel={t('common.select_player', 'Select player')}
              placeholder={t('auto.ConditionPage.k2')}
              className="w-full sm:min-w-[280px] sm:max-w-md"
            />
          </div>
        )}
      </div>

      {/* ダウンロードボタン */}
      {effectivePlayerId && (
        <div className={`px-6 py-2 flex items-center justify-end gap-1.5 border-b ${borderColor}`}>
          <MIcon name="file_download" size={13} className={textMuted} />
          <button
            onClick={() => dlReport(`/api/reports/condition_pdf?player_id=${effectivePlayerId}`, `condition_${effectivePlayerId}.pdf`)}
            className={`text-xs px-2.5 py-1 rounded-ss-md border transition-colors ${'border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]'}`}
          >
            {t('auto.ConditionPage.k5')}
          </button>
          <button
            onClick={() => dlReport(`/api/reports/condition?player_id=${effectivePlayerId}`, `condition_${effectivePlayerId}.json`)}
            className={`text-xs px-2.5 py-1 rounded-ss-md border transition-colors ${'border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]'}`}
          >
            {t('auto.ConditionPage.k6')}
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
              className={`flex-shrink-0 px-3 py-1.5 rounded-ss-md text-xs font-medium whitespace-nowrap transition-colors ${
                subtab === k
                  ? 'bg-[var(--ss-brand)] text-white'
                  : 'text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]'
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
            {/* 3. 体調タブヘッダ: 実データ起点の advice strip */}
            {effectivePlayerId && (
              <AdviceStrip context="condition.header" playerId={effectivePlayerId} />
            )}

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
        ) : !authPlayerId ? (
          // 入力タブ: ログインユーザが選手として登録されていない (coach / analyst /
          // admin で player_id 未紐付) 場合、コンディション入力は無効。
          // 過去仕様: 選択した選手の代理入力ができていたが、誰のデータか曖昧になる
          // ため廃止 (2026-05-19)。
          <div className={`max-w-2xl p-4 rounded-ss-lg border ${borderColor} ${panelBg}`}>
            <div className="flex items-start gap-2">
              <div className="text-xs leading-relaxed" style={{ color: 'var(--ss-t2)' }}>
                <div className="font-semibold mb-1">
                  {t('auto.ConditionPage.k7')}
                </div>
                <p>
                  {t('auto.ConditionPage.k8')}
                </p>
                <p className="mt-2">
                  {t('auto.ConditionPage.k9')}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-5 max-w-4xl">
            {/* 入力対象明示: 必ず「自分自身」(authPlayerId) のレコードになる。
               選択した選手の代理入力はできない設計 (誰が入力したか曖昧になるのを防ぐ)。 */}
            <div
              className="text-xs px-3 py-2 rounded-ss-md border"
              style={{
                color: 'var(--ss-brand)',
                backgroundColor: 'var(--ss-brand-tint)',
                borderColor: 'var(--ss-brand)',
              }}
            >
              {t('auto.ConditionPage.k10')} <strong>{t('auto.ConditionPage.k3')}</strong> (
              {players.find((p) => p.id === authPlayerId)?.name ?? t('auto.ConditionPage.k11', { n: authPlayerId })}
              {t('auto.ConditionPage.k12')}
            </div>

            {/* モード切替 */}
            <div className="flex overflow-x-auto scrollbar-hide gap-1">
              {availableModes.map((m) => (
                <button
                  key={m}
                  onClick={() => { setMode(m); setLatestResult(null); setSuccessMsg(null); setErrorMsg(null) }}
                  className={`flex-shrink-0 px-3 py-1.5 rounded-ss-md text-xs font-medium whitespace-nowrap transition-colors ${
                    mode === m
                      ? 'bg-[var(--ss-brand)] text-white'
                      : 'text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)] border border-[var(--ss-border)]'
                  }`}
                >
                  {t(`condition.mode.${m}`)}
                </button>
              ))}
            </div>

            {/* 測定日 */}
            <div className="flex items-center gap-3">
              <label className={`text-xs ${textMuted} shrink-0`}>
                {t('auto.ConditionPage.k13')}
              </label>
              <input
                type="date"
                className={
                  'border border-[var(--ss-border-strong)] bg-[var(--ss-surface-1)] text-[var(--ss-t1)] rounded-ss-md px-2 py-1.5 text-sm'
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
                playerId={authPlayerId!}
                measuredAt={measuredAt}
                isLight={isLight}
                onSubmitted={handleQuestionnaireSubmitted}
              />
            )}

            {mode === 'prematch' && (
              <PreMatchQuestionnaire
                playerId={authPlayerId!}
                measuredAt={measuredAt}
                isLight={isLight}
                onSubmitted={handleQuestionnaireSubmitted}
              />
            )}

            {mode === 'body' && role !== 'player' && (
              <>
                <section className={`rounded-ss-lg border ${borderColor} ${panelBg} p-4`}>
                  <h2 className="text-sm font-semibold mb-3">{t('condition.section_inbody')}</h2>
                  <InBodyForm value={formState} onChange={patch} isLight={isLight} />
                </section>

                <section className={`rounded-ss-lg border ${borderColor} ${panelBg} p-4`}>
                  <h2 className="text-sm font-semibold mb-3">{t('condition.section_hooper_rpe')}</h2>
                  <HooperRpeForm value={formState} onChange={patch} isLight={isLight} />
                </section>

                <section className={`rounded-ss-lg border ${borderColor} ${panelBg} p-4`}>
                  <h2 className="text-sm font-semibold mb-3">{t('condition.section_auxiliary')}</h2>
                  <AuxiliaryForm value={formState} onChange={patch} isLight={isLight} />
                </section>

                {errorMsg && (
                  <div className="text-sm text-[var(--ss-bad)] bg-[var(--ss-danger-tint)] border border-[var(--ss-danger-border)] rounded-ss-md px-3 py-2">
                    {errorMsg}
                  </div>
                )}
                {successMsg && (
                  <div className="text-sm text-[var(--ss-success)] bg-[var(--ss-success-tint)] border border-[var(--ss-success-border)] rounded-ss-md px-3 py-2">
                    {successMsg}
                  </div>
                )}

                <div className="flex justify-end">
                  <button
                    onClick={handleBodySubmit}
                    disabled={createMut.isPending}
                    className="px-4 py-2 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] disabled:opacity-50 text-white rounded-ss-md text-sm font-medium"
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

      {/* CCS / F1-F5 / Hooper / RPE などの用語解説 */}
      <ConditionGlossary open={glossaryOpen} onClose={() => setGlossaryOpen(false)} />
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
  const muted = 'text-[var(--ss-t3)]'
  const panelCls = 'bg-[var(--ss-surface-1)] border-[var(--ss-border)]'
  const filterBtnBase = 'px-3 py-1 rounded-ss-md text-xs font-medium transition-colors'
  const filterBtnOff = 'text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)] border border-[var(--ss-border)]'

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
        <div className="flex flex-wrap gap-1">
          {filterOpts.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setFilter(opt.key)}
              className={`${filterBtnBase} ${filter === opt.key ? 'bg-[var(--ss-brand)] text-white' : filterBtnOff}`}
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
              className={`border rounded-ss-lg ${panelCls} hover:opacity-90 transition-opacity`}
            >
              <button
                onClick={() => onSelect(r as unknown as Record<string, unknown>)}
                className="w-full text-left px-3 py-2"
              >
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium num-cell ss-num">{r.measured_at ?? ''}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-ss-sm border ${'border-[var(--ss-border-strong)] text-[var(--ss-t2)]'}`}>
                      {typeLabel(r.condition_type)}
                    </span>
                  </div>
                  {/* xs: 2 列 grid (5 指標は 3 行で安定)、sm+: 横並び flex-wrap で 1-2 行に */}
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 sm:flex sm:flex-wrap sm:items-center sm:gap-x-3 sm:gap-y-1 text-xs num-cell ss-num">
                    {r.ccs != null && (
                      <span>{t('condition.history.ccs')}: <span className="text-[var(--ss-brand)]">{fmt(r.ccs)}</span></span>
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
                  <div className={`mt-1 grid grid-cols-3 gap-x-3 gap-y-1 sm:flex sm:gap-3 text-[11px] num-cell ss-num ${muted}`}>
                    {(['f1', 'f2', 'f3', 'f4', 'f5'] as const).map((k) => {
                      const v = r[k] as number | null | undefined
                      return (
                        <span key={k}>
                          {k.toUpperCase()}: <span className={'text-[var(--ss-t1)]'}>{fmt(v)}</span>
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
                    className="flex items-center gap-1 text-[11px] text-[var(--ss-bad)] hover:opacity-80 disabled:opacity-50"
                  >
                    <MIcon name="delete" size={12} />
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
