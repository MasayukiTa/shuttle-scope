import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getMyConsents, withdrawConsent, submitConsents, type ConsentType } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'

/**
 * ユーザが任意同意を撤回できる UI。GDPR Article 7(3) /
 * APPI 第18条 4 項の「同意取得と同じくらい容易に撤回可能」要件を満たすため
 * SettingsPage 内 account タブから到達可能にする。
 *
 * 必須同意 (service_delivery / beta_agreement) は contractual basis であり
 * 撤回不可。表示のみで「アカウント削除が必要」と案内する。
 *
 * 任意同意 (ai_training / research_participation / cross_border_transfer)
 * は撤回ボタン押下 → 確認ダイアログ → DELETE /api/auth/consents/{type}。
 */
export function ConsentManagementCard({ isLight }: { isLight: boolean }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [pending, setPending] = useState<ConsentType | null>(null)

  const consentQuery = useQuery({
    queryKey: ['my-consents'],
    queryFn: getMyConsents,
    staleTime: 30_000,
  })

  const withdrawMutation = useMutation({
    mutationFn: (type: ConsentType) => withdrawConsent(type),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['my-consents'] })
      setPending(null)
    },
  })

  // 再承認 mutation: 撤回後に再度同意を付与できる (GDPR Article 7(3) は
  // 撤回が容易であることを要求するが、撤回後の再付与を妨げる規定はない。
  // むしろ「いつでも撤回・再付与できる」のがユーザ自決の本来形)
  const regrantMutation = useMutation({
    mutationFn: async (type: ConsentType) => {
      const current = consentQuery.data?.data
      if (!current) throw new Error('consent state not loaded')
      return submitConsents({
        consents: [{ consent_type: type, consent_given: true }],
        privacy_policy_version: current.current_versions.privacy_policy,
        terms_version: current.current_versions.terms,
      })
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['my-consents'] })
      setPending(null)
    },
  })

  if (consentQuery.isLoading) {
    return (
      <section>
        <h2 className={`text-lg font-medium mb-1 text-[var(--ss-t1)]`}>
          {t('settings.consent.title', '同意状態')}
        </h2>
        <div className="flex items-center gap-2 text-sm text-[var(--ss-t3)] mt-2">
          <MIcon name="progress_activity" size={14} className="animate-spin" />
          {t('common.loading', '読み込み中…')}
        </div>
      </section>
    )
  }

  if (consentQuery.error || !consentQuery.data) {
    return null
  }

  const data = consentQuery.data.data
  const requiredTypes = new Set<ConsentType>(data.required_types)
  // 既存 consent record (要素なら given_at/withdrawn_at を持つ) を type 別に lookup
  const consentByType = new Map(data.consents.map((c) => [c.consent_type, c]))

  const allTypes: ConsentType[] = [
    ...data.required_types,
    ...data.optional_types,
  ]

  function handleWithdraw(type: ConsentType) {
    const ok = window.confirm(
      t(
        'settings.consent.confirm_withdraw',
        '同意「{{type}}」を撤回します。よろしいですか？\n\n' +
          '撤回後、関連する処理（AI モデル学習等）から除外されます。' +
          '撤回履歴は GDPR / APPI の monitoring 目的で保管されます。',
        { type: t(`settings.consent.types.${type}`, type) }
      )
    )
    if (!ok) return
    setPending(type)
    withdrawMutation.mutate(type)
  }

  function handleRegrant(type: ConsentType) {
    setPending(type)
    regrantMutation.mutate(type)
  }

  const cardCls = `rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-4`

  return (
    <section>
      <h2 className={`text-lg font-medium mb-1 text-[var(--ss-t1)]`}>
        {t('settings.consent.title', '同意状態と撤回')}
      </h2>
      <p className={`text-xs mb-3 text-[var(--ss-t3)]`}>
        {t(
          'settings.consent.description',
          '任意同意は GDPR Article 7(3) / APPI 第18条に基づきいつでも撤回できます。' +
            '必須同意（契約履行）は、撤回するにはアカウント削除が必要です。'
        )}
      </p>

      <div className={cardCls}>
        <div className="space-y-3">
          {allTypes.map((type) => {
            const isRequired = requiredTypes.has(type)
            const rec = consentByType.get(type)
            const isWithdrawn = !rec || !rec.consent_given || !!rec.withdrawn_at
            return (
              <div
                key={type}
                className={`flex items-start justify-between gap-3 pb-3 border-b last:border-b-0 border-[var(--ss-border)]`}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* 状態 pill: ON は塗りつぶし Cool blue / OFF は塗りつぶし gray
                        どちらも solid 塗りで「色弱でも一目でわかる」コントラストにする */}
                    {isWithdrawn ? (
                      <span
                        className="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded"
                        style={{ background: '#6b7280', color: '#fff' }}
                      >
                        {t('settings.consent.status_off', 'NOT GRANTED')}
                      </span>
                    ) : (
                      <span
                        className="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded"
                        style={{ background: '#3b4cc0', color: '#fff' }}
                      >
                        {t('settings.consent.status_on', 'GRANTED')}
                      </span>
                    )}
                    <span className={`text-sm font-medium text-[var(--ss-t1)]`}>
                      {t(`settings.consent.types.${type}`, type)}
                    </span>
                    {isRequired ? (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-ss-sm border bg-[var(--ss-brand-tint)] text-[var(--ss-brand)] border-[var(--ss-brand)]`}>
                        {t('settings.consent.required_label', '契約履行（必須）')}
                      </span>
                    ) : (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-ss-sm border bg-[var(--ss-surface-2)] text-[var(--ss-t2)] border-[var(--ss-border)]`}>
                        {t('settings.consent.optional_label', '任意')}
                      </span>
                    )}
                  </div>
                  {rec?.given_at && !isWithdrawn && (
                    <div className={`text-xs mt-1 text-[var(--ss-t3)]`}>
                      {t('settings.consent.granted_on', '承認日')}: {new Date(rec.given_at).toLocaleDateString()}
                    </div>
                  )}
                  {rec?.withdrawn_at && (
                    <div className={`text-xs mt-1 text-[var(--ss-t3)]`}>
                      {t('settings.consent.withdrawn_label', '撤回済み')}: {new Date(rec.withdrawn_at).toLocaleDateString()}
                    </div>
                  )}
                </div>

                <div className="flex items-center">
                  {isRequired ? (
                    <span
                      className={`flex items-center gap-1 text-xs text-[var(--ss-t3)]`}
                    >
                      <MIcon name="error" size={12} />
                      {t('settings.consent.required_note', '撤回不可')}
                    </span>
                  ) : isWithdrawn ? (
                    // 撤回後の再承認ボタン (一方向ではなく双方向に修正、2026-05-19)
                    // GDPR Art 7(3) は撤回の容易性を要求するが、再付与を妨げない。
                    <button
                      onClick={() => handleRegrant(type)}
                      disabled={pending === type}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-ss-md text-xs font-medium border border-[var(--ss-border)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)] transition-colors duration-base ease-out ${pending === type ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {pending === type ? (
                        <MIcon name="progress_activity" size={12} className="animate-spin" />
                      ) : (
                        <MIcon name="check" size={12} />
                      )}
                      {t('settings.consent.regrant_btn', '再承認')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleWithdraw(type)}
                      disabled={pending === type}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-ss-md text-xs font-medium border border-[var(--ss-danger-border)] text-[var(--ss-danger-text)] hover:bg-[var(--ss-danger-bg)] transition-colors duration-base ease-out ${pending === type ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {pending === type ? (
                        <MIcon name="progress_activity" size={12} className="animate-spin" />
                      ) : (
                        <MIcon name="check" size={12} />
                      )}
                      {t('settings.consent.withdraw_btn', '撤回')}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {withdrawMutation.isError && (
          <div className="mt-3 text-xs text-[var(--ss-danger-text)]">
            {t('settings.consent.error', '撤回に失敗しました。再試行してください。')}
          </div>
        )}
      </div>
    </section>
  )
}
