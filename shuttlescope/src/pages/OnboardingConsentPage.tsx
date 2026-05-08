/**
 * OnboardingConsentPage
 *
 * GDPR Article 7 / APPI 第18条 準拠の同意取得画面。
 * 初回ログイン or 文書改定後に表示し、必須同意 (service_delivery / beta_agreement)
 * + 任意同意 (ai_training / research_participation / cross_border_transfer) を
 * 個別 checkbox で取得する (GDPR Article 7(2): independent specific consent)。
 *
 * 表示テキストは i18n keys を経由する (CLAUDE.md ルール)。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ConsentRecord,
  ConsentStateDTO,
  ConsentType,
  getMyConsents,
  submitConsents,
} from '@/api/client'

const REQUIRED: ConsentType[] = ['service_delivery', 'beta_agreement']
const OPTIONAL: ConsentType[] = ['ai_training', 'research_participation', 'cross_border_transfer']

interface OnboardingConsentPageProps {
  onCompleted: () => void
}

export default function OnboardingConsentPage({ onCompleted }: OnboardingConsentPageProps) {
  const { t } = useTranslation()
  const [state, setState] = useState<ConsentStateDTO | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 同意状態。initial は false、ユーザーが明示的にチェックしない限り送信されない。
  const [given, setGiven] = useState<Record<ConsentType, boolean>>({
    service_delivery: false,
    beta_agreement: false,
    ai_training: false,
    research_participation: false,
    cross_border_transfer: false,
  })

  useEffect(() => {
    let cancelled = false
    getMyConsents()
      .then((r) => {
        if (cancelled) return
        setState(r.data)
        // 既存の同意状態を反映 (再同意要求時の利便性、必須は手動チェックを再要求)
        const existing: Record<string, ConsentRecord> = {}
        for (const c of r.data.consents) existing[c.consent_type] = c
        setGiven((prev) => {
          const next = { ...prev }
          for (const t of OPTIONAL) {
            if (existing[t]?.consent_given) next[t] = true
          }
          return next
        })
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const allRequiredChecked = useMemo(
    () => REQUIRED.every((t) => given[t] === true),
    [given]
  )

  const onSubmit = async () => {
    if (!state) return
    if (!allRequiredChecked) {
      setError(t('onboarding.consent.error_required_missing') || '必須同意項目にすべてチェックを入れてください')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const consents = [...REQUIRED, ...OPTIONAL].map((t) => ({
        consent_type: t,
        consent_given: !!given[t],
      }))
      await submitConsents({
        consents,
        privacy_policy_version: state.current_versions.privacy_policy,
        terms_version: state.current_versions.terms,
      })
      onCompleted()
    } catch (e) {
      setError((e as Error).message || t('onboarding.consent.error_submit') || '同意送信に失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-gray-700 dark:text-gray-200">{t('common.loading') || 'Loading...'}</div>
      </div>
    )
  }

  if (!state) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-red-600">{error || 'Failed to load consent state'}</div>
      </div>
    )
  }

  const ppv = state.current_versions.privacy_policy
  const tv = state.current_versions.terms

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 py-8 px-4">
      <div className="max-w-3xl mx-auto bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6">
        <header className="border-b border-gray-200 dark:border-gray-700 pb-4">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {t('onboarding.consent.title') || 'データ取り扱いに関する同意'}
          </h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
            {t('onboarding.consent.intro') ||
              '本サービス (ShuttleScope) のご利用にあたり、以下の文書をお読みいただき、同意の可否をご判断ください。同意は任意であり、いつでも撤回できます。'}
          </p>
          <ul className="mt-3 text-sm space-y-1">
            <li>
              <a
                href="https://github.com/MasayukiTa/shuttle-scope/blob/main/PRIVACY.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline dark:text-blue-400"
              >
                Privacy Notice (Version {ppv})
              </a>
            </li>
            <li>
              <a
                href="https://github.com/MasayukiTa/shuttle-scope/blob/main/TERMS_OF_SERVICE.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline dark:text-blue-400"
              >
                Terms of Service (Version {tv})
              </a>
            </li>
            <li>
              <a
                href="https://github.com/MasayukiTa/shuttle-scope/blob/main/DATA_CONTRIBUTION_TERMS.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline dark:text-blue-400"
              >
                Data Contribution Terms
              </a>
            </li>
          </ul>
        </header>

        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('onboarding.consent.required_section') || '必須同意項目'}
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {t('onboarding.consent.required_hint') ||
              'これらに同意いただかないと本サービスをご利用いただけません。'}
          </p>

          <ConsentCheckbox
            checked={given.service_delivery}
            onChange={(v) => setGiven((g) => ({ ...g, service_delivery: v }))}
            label={t('onboarding.consent.service_delivery_label') || 'サービス提供のためのデータ処理に同意します'}
            description={
              t('onboarding.consent.service_delivery_desc') ||
              '試合データ・選手プロフィール・解析結果の処理。本サービス利用のため必須。'
            }
            required
          />

          <ConsentCheckbox
            checked={given.beta_agreement}
            onChange={(v) => setGiven((g) => ({ ...g, beta_agreement: v }))}
            label={t('onboarding.consent.beta_agreement_label') || 'β版データ取り扱い説明書の内容を読み、理解しました'}
            description={
              t('onboarding.consent.beta_agreement_desc') ||
              '別途提供されている β 期間中のデータ取り扱い説明書 (RBC_BETA_AGREEMENT) を読了したことを表明します。'
            }
            required
          />
        </section>

        <section className="space-y-4 border-t border-gray-200 dark:border-gray-700 pt-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('onboarding.consent.optional_section') || '任意同意項目 (チェックしなくても本サービスは使えます)'}
          </h2>

          <ConsentCheckbox
            checked={given.ai_training}
            onChange={(v) => setGiven((g) => ({ ...g, ai_training: v }))}
            label={t('onboarding.consent.ai_training_label') || 'AI モデル学習への利用に同意します'}
            description={
              t('onboarding.consent.ai_training_desc') ||
              '匿名化・集計化されたデータを将来的な精度向上モデル学習に利用します。撤回時は以後の学習対象から除外されます。'
            }
          />

          <ConsentCheckbox
            checked={given.research_participation}
            onChange={(v) => setGiven((g) => ({ ...g, research_participation: v }))}
            label={t('onboarding.consent.research_label') || '学術研究への利用に同意します'}
            description={
              t('onboarding.consent.research_desc') ||
              '匿名化のうえスポーツ科学研究、論文発表等への利用を許可します。事前説明・同意撤回権を保持します。'
            }
          />

          <ConsentCheckbox
            checked={given.cross_border_transfer}
            onChange={(v) => setGiven((g) => ({ ...g, cross_border_transfer: v }))}
            label={t('onboarding.consent.cross_border_label') || '越境データ移転 (EU/EEA/北米遠征時) に同意します'}
            description={
              t('onboarding.consent.cross_border_desc') ||
              '海外遠征時の現地解析および日本の本サービスサーバーへの転送について GDPR / APPI 等の保護措置を前提に同意します。'
            }
          />
        </section>

        {error ? (
          <div className="text-sm text-red-600 dark:text-red-400 border border-red-200 dark:border-red-700/50 rounded p-3">
            {error}
          </div>
        ) : null}

        <footer className="flex flex-col-reverse sm:flex-row gap-3 sm:justify-end pt-4 border-t border-gray-200 dark:border-gray-700">
          <button
            type="button"
            disabled={!allRequiredChecked || submitting}
            onClick={onSubmit}
            className="px-4 py-2 rounded bg-blue-600 text-white font-medium disabled:bg-gray-400 hover:bg-blue-700 transition"
          >
            {submitting
              ? t('onboarding.consent.submitting') || '送信中...'
              : t('onboarding.consent.submit') || '同意して開始'}
          </button>
        </footer>

        <p className="text-xs text-gray-500 dark:text-gray-400 pt-2">
          {t('onboarding.consent.withdraw_notice') ||
            '同意は本ページもしくは設定画面からいつでも撤回できます。任意同意の撤回は本サービスの利用に影響しません。'}
        </p>
      </div>
    </div>
  )
}

function ConsentCheckbox({
  checked,
  onChange,
  label,
  description,
  required,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  description: string
  required?: boolean
}) {
  return (
    <label className="flex items-start gap-3 p-3 rounded border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-5 w-5 text-blue-600 rounded"
      />
      <div className="flex-1">
        <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
          {label}
          {required ? <span className="ml-2 text-red-600 text-xs">必須</span> : null}
        </div>
        <p className="mt-1 text-xs text-gray-600 dark:text-gray-300">{description}</p>
      </div>
    </label>
  )
}
