import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X, AlertCircle, Loader2 } from 'lucide-react'
import { getMyConsents, withdrawConsent, type ConsentType } from '@/api/client'

/**
 * ユーザーが任意同意を撤回できる UI。GDPR Article 7(3) /
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

  if (consentQuery.isLoading) {
    return (
      <section>
        <h2 className={`text-lg font-medium mb-1 ${isLight ? 'text-gray-900' : 'text-white'}`}>
          {t('settings.consent.title', '同意状態')}
        </h2>
        <div className="flex items-center gap-2 text-sm text-gray-500 mt-2">
          <Loader2 size={14} className="animate-spin" />
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

  const cardCls = `rounded-lg border p-4 ${
    isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-800'
  }`

  return (
    <section>
      <h2 className={`text-lg font-medium mb-1 ${isLight ? 'text-gray-900' : 'text-white'}`}>
        {t('settings.consent.title', '同意状態と撤回')}
      </h2>
      <p className={`text-xs mb-3 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
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
                className={`flex items-start justify-between gap-3 pb-3 border-b last:border-b-0 ${
                  isLight ? 'border-gray-200' : 'border-gray-700'
                }`}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${isLight ? 'text-gray-900' : 'text-white'}`}>
                      {t(`settings.consent.types.${type}`, type)}
                    </span>
                    {isRequired ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/40">
                        {t('settings.consent.required_label', '契約履行（必須）')}
                      </span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400 border border-gray-500/40">
                        {t('settings.consent.optional_label', '任意')}
                      </span>
                    )}
                  </div>
                  <div className={`text-xs mt-1 ${isLight ? 'text-gray-500' : 'text-gray-400'}`}>
                    {isWithdrawn
                      ? t('settings.consent.state_withdrawn', '未付与または撤回済')
                      : t('settings.consent.state_active', '有効')}
                    {rec?.given_at && (
                      <span className="ml-2 opacity-70">
                        {new Date(rec.given_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center">
                  {isRequired ? (
                    <span
                      className={`flex items-center gap-1 text-xs ${
                        isLight ? 'text-gray-500' : 'text-gray-400'
                      }`}
                    >
                      <AlertCircle size={12} />
                      {t('settings.consent.required_note', '撤回不可')}
                    </span>
                  ) : isWithdrawn ? (
                    <span
                      className={`flex items-center gap-1 text-xs ${
                        isLight ? 'text-gray-500' : 'text-gray-400'
                      }`}
                    >
                      <X size={12} />
                      {t('settings.consent.withdrawn_label', '撤回済み')}
                    </span>
                  ) : (
                    <button
                      onClick={() => handleWithdraw(type)}
                      disabled={pending === type}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border transition-colors ${
                        isLight
                          ? 'border-red-300 text-red-700 hover:bg-red-50'
                          : 'border-red-600 text-red-400 hover:bg-red-900/20'
                      } ${pending === type ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {pending === type ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Check size={12} />
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
          <div className="mt-3 text-xs text-red-400">
            {t('settings.consent.error', '撤回に失敗しました。再試行してください。')}
          </div>
        )}
      </div>
    </section>
  )
}
