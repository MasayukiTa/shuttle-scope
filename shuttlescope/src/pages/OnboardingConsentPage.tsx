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

// 必須項目は GDPR Article 6(1)(b) (契約履行) / APPI 第18条 を法的根拠とし、
// 「同意」ではなく「契約条項の確認」として扱う。撤回はサービス利用終了と等価。
const REQUIRED: ConsentType[] = ['service_delivery', 'beta_agreement']
// 任意項目は GDPR Article 6(1)(a) (同意) / APPI 同意。independent specific consent
// per Article 7(2)。撤回は contact@shuttle-scope.com / 問い合わせフォーム経由。
// cross_border_transfer は EU-Japan 十分性認定 (2019-01) により追加同意不要のため
// UI 提示しない (CONSENT_UI_LEGAL_ANALYSIS §2.5 選択肢 A 採用)。
// body_disclose_to_analyst / body_disclose_to_coach: 体組成データ (Tier 3) の
// 開示先制御。default 表示は ON (β期間運用ポリシー)、設定でいつでも変更可。
const OPTIONAL: ConsentType[] = [
  'ai_training',
  'research_participation',
  'body_disclose_to_analyst',
  'body_disclose_to_coach',
]

interface OnboardingConsentPageProps {
  onCompleted: () => void
  // optionalOnly: 必須同意は既に取得済で、任意同意のみ未回答が残っているケース。
  //   - 必須セクションは hide
  //   - 「あとで」ボタンが表示される
  optionalOnly?: boolean
  // 「あとで」が押された時の callback (App.tsx で popup を閉じる、optional は未提出)。
  onDeferred?: () => void
}

export default function OnboardingConsentPage({
  onCompleted, optionalOnly, onDeferred,
}: OnboardingConsentPageProps) {
  const { t, i18n } = useTranslation()
  const [state, setState] = useState<ConsentStateDTO | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 文書 popup. null = 閉、'privacy' / 'terms' = 表示中
  const [docModal, setDocModal] = useState<null | 'privacy' | 'terms'>(null)

  // 同意/確認状態。initial は false、ユーザーが明示的にチェックしない限り送信されない。
  const [given, setGiven] = useState<Record<ConsentType, boolean>>({
    service_delivery: false,
    beta_agreement: false,
    ai_training: false,
    research_participation: false,
    // cross_border_transfer は UI に出さないが backend 側の互換のため keep。
    // 送信時は false のまま (撤回扱い) で送り、backend は OPTIONAL として記録する。
    cross_border_transfer: false,
    // 体組成データの開示: β期間運用方針として default ON で表示する。
    // ユーザが見たうえで OFF にしたければチェックを外せる (= consent withdraw)。
    body_disclose_to_analyst: true,
    body_disclose_to_coach: true,
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
  // optionalOnly mode: 必須は backend で既に取得済 → check 不要、submit 時にも送らない。
  const canSubmit = optionalOnly ? true : allRequiredChecked

  const onSubmit = async () => {
    if (!state) return
    if (!optionalOnly && !allRequiredChecked) {
      setError(t('onboarding.consent.error_required_missing') || '必須同意項目にすべてチェックを入れてください')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      // optionalOnly: optional のみ submit (必須は既に backend にある)。
      const types = optionalOnly ? OPTIONAL : [...REQUIRED, ...OPTIONAL]
      const consents = types.map((t) => ({
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
          <div className="flex items-start justify-between gap-3">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {t('onboarding.consent.title') || 'データ取り扱いに関する確認・同意'}
            </h1>
            {/* 言語切替: site-wide な i18n を即座に変更。GitHub に access 出来ない
               選手も使うため、popup 内で完結する操作に統一。 */}
            <div className="shrink-0 flex items-center gap-1 text-xs">
              <button
                type="button"
                onClick={() => i18n.changeLanguage('ja')}
                className={`px-2 py-1 rounded border ${
                  (i18n.language as string)?.startsWith('ja')
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'
                }`}
              >日本語</button>
              <button
                type="button"
                onClick={() => i18n.changeLanguage('en')}
                className={`px-2 py-1 rounded border ${
                  (i18n.language as string)?.startsWith('en')
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'
                }`}
              >EN</button>
            </div>
          </div>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
            {t('onboarding.consent.intro') ||
              '本サービス (ShuttleScope) のご利用にあたり、以下の文書をお読みいただき、内容をご確認の上、任意同意項目について同意の可否をご判断ください。'}
          </p>
          {/* GitHub リンクは廃止。社内/学校ネットワークから github が見えないユーザも
             居るため、backend が serve している HTML を popup modal に iframe で表示。
             /privacy /terms (JA), /en/privacy /en/terms (EN) — i18n.language で出し分け。 */}
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            <button
              type="button"
              onClick={() => setDocModal('privacy')}
              className="px-3 py-1.5 rounded border border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30"
            >
              {t('onboarding.consent.view_privacy') || 'プライバシーポリシーを表示'} (v{ppv})
            </button>
            <button
              type="button"
              onClick={() => setDocModal('terms')}
              className="px-3 py-1.5 rounded border border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30"
            >
              {t('onboarding.consent.view_terms') || '利用規約を表示'} (v{tv})
            </button>
          </div>
        </header>

        {/* optionalOnly mode では必須セクションを丸ごと hide。次回ログイン時に
           任意同意の再確認だけしたい人 (「あとで」を押した人) 用。 */}
        <section className={`space-y-4 ${optionalOnly ? 'hidden' : ''}`}>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('onboarding.consent.required_section') || '必須確認事項（契約履行に基づく処理）'}
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {t('onboarding.consent.required_hint') ||
              'これらに同意いただかないと本サービスをご利用いただけません。これらは GDPR Article 6(1)(b)（契約履行）および APPI 第18条に基づく処理であり、撤回はサービス利用の終了と等価となります。'}
          </p>

          <ConsentCheckbox
            checked={given.service_delivery}
            onChange={(v) => setGiven((g) => ({ ...g, service_delivery: v }))}
            label={t('onboarding.consent.service_delivery_label') || 'Privacy Notice および Terms of Service の内容を確認しました'}
            description={
              t('onboarding.consent.service_delivery_desc') ||
              'これらの文書に記載されたデータ処理（試合データ・選手プロフィール・解析結果の処理、認証、監査ログ等）は本サービス提供に必要な処理であり、GDPR Article 6(1)(b) および APPI 第18条に基づき行われます。これらの処理を停止する場合はサービスの利用終了をお選びください。'
            }
            required
          />

          <ConsentCheckbox
            checked={given.beta_agreement}
            onChange={(v) => setGiven((g) => ({ ...g, beta_agreement: v }))}
            label={t('onboarding.consent.beta_agreement_label') || 'β版データ取り扱い説明書（Terms of Service Section 14）の内容を確認しました'}
            description={
              t('onboarding.consent.beta_agreement_desc') ||
              'β期間中のデータ利用範囲、目的、保管期間、第三者提供の有無について記載された文書を読了したことを表明します。Terms of Service Section 14.5 の規定により、β期間中のデータ利用への異議申立ては問い合わせフォーム経由で随時受け付けます。'
            }
            required
          />
        </section>

        <section className="space-y-4 border-t border-gray-200 dark:border-gray-700 pt-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('onboarding.consent.optional_section') || '任意同意事項（チェックしなくても本サービスは使えます）'}
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {t('onboarding.consent.optional_hint') ||
              '以下の任意同意は GDPR Article 6(1)(a) / APPI に基づく同意です。撤回はお問い合わせフォームまたは contact@shuttle-scope.com 宛てメールで受け付けます（受領から 14 日以内に処理）。'}
          </p>

          <ConsentCheckbox
            checked={given.ai_training}
            onChange={(v) => setGiven((g) => ({ ...g, ai_training: v }))}
            label={t('onboarding.consent.ai_training_label') || 'AI モデル学習への利用に同意します'}
            description={
              t('onboarding.consent.ai_training_desc') ||
              '匿名化・集計化されたデータを将来的なモデル精度向上のために利用します。同意は任意であり、いつでも撤回できます。撤回時は以後の学習対象から除外されます。撤回方法：お問い合わせフォーム（https://shuttle-scope.com/contact）または contact@shuttle-scope.com 宛てメール。'
            }
          />

          <ConsentCheckbox
            checked={given.research_participation}
            onChange={(v) => setGiven((g) => ({ ...g, research_participation: v }))}
            label={t('onboarding.consent.research_label') || '学術研究への利用に同意します'}
            description={
              t('onboarding.consent.research_desc') ||
              '匿名化のうえスポーツ科学研究、論文発表等への利用を許可します。事前説明と同意撤回権を保持します。撤回方法：お問い合わせフォーム（https://shuttle-scope.com/contact）または contact@shuttle-scope.com 宛てメール。'
            }
          />

          <ConsentCheckbox
            checked={given.body_disclose_to_analyst}
            onChange={(v) => setGiven((g) => ({ ...g, body_disclose_to_analyst: v }))}
            label={t('onboarding.consent.body_disclose_to_analyst_label') || '体組成データをアナリストに開示します'}
            description={
              t('onboarding.consent.body_disclose_to_analyst_desc') ||
              '体重・体脂肪率・筋肉量等のデータをチーム解析担当 (analyst) に開示します。default は ON ですが、いつでも設定画面 (体調タブ) からトグルで変更できます。'
            }
          />

          <ConsentCheckbox
            checked={given.body_disclose_to_coach}
            onChange={(v) => setGiven((g) => ({ ...g, body_disclose_to_coach: v }))}
            label={t('onboarding.consent.body_disclose_to_coach_label') || '体組成データをコーチに開示します'}
            description={
              t('onboarding.consent.body_disclose_to_coach_desc') ||
              '体重・体脂肪率・筋肉量等のデータをコーチに開示します。default は ON ですが、いつでも設定画面 (体調タブ) からトグルで変更できます。'
            }
          />
        </section>

        {error ? (
          <div className="text-sm text-red-600 dark:text-red-400 border border-red-200 dark:border-red-700/50 rounded p-3">
            {error}
          </div>
        ) : null}

        <footer className="flex flex-col-reverse sm:flex-row gap-3 sm:justify-end pt-4 border-t border-gray-200 dark:border-gray-700">
          {/* 「あとで見るよ」: 必須同意 (= 初回 mode) も含めて全 mode で表示する。
             - 初回 mode: 必須が check 済なら submit (required のみ) + 任意は skip。
               必須未 check なら error 表示。次回ログインで再 popup。
             - optionalOnly: rows 書き込まずに popup 閉じ。次回再 popup。
             配置: 「確認・同意して開始」の **左**。 */}
          <button
            type="button"
            disabled={submitting}
            onClick={async () => {
              if (optionalOnly) {
                // 何も書き込まず popup を閉じる
                onDeferred?.()
                return
              }
              // 初回 mode: 必須を submit し optional は skip → 次回 popup で再促し
              if (!state) return
              if (!allRequiredChecked) {
                setError(t('onboarding.consent.error_required_missing') || '必須同意項目にすべてチェックを入れてください')
                return
              }
              setSubmitting(true)
              setError(null)
              try {
                const consents = REQUIRED.map((t) => ({
                  consent_type: t,
                  consent_given: true,
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
            }}
            className="px-4 py-2 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 font-medium hover:bg-gray-100 dark:hover:bg-gray-700 transition"
          >
            {t('onboarding.consent.later') || 'あとで見るよ'}
          </button>
          <button
            type="button"
            disabled={!canSubmit || submitting}
            onClick={onSubmit}
            className="px-4 py-2 rounded bg-blue-600 text-white font-medium disabled:bg-gray-400 hover:bg-blue-700 transition"
          >
            {submitting
              ? t('onboarding.consent.submitting') || '送信中...'
              : optionalOnly
                ? (t('onboarding.consent.submit_optional') || '回答して保存')
                : (t('onboarding.consent.submit') || '確認・同意して開始')}
          </button>
        </footer>

        <p className="text-xs text-gray-500 dark:text-gray-400 pt-2">
          {t('onboarding.consent.withdraw_notice') ||
            '必須確認事項は契約履行のため撤回は行えません（撤回はサービス利用終了と等価です）。任意同意は 設定 → 体調タブ → 体組成データの開示設定、またはお問い合わせフォーム / contact@shuttle-scope.com 宛てメールでいつでも変更・撤回できます。'}
        </p>
      </div>

      {/* 文書 popup modal. iframe で backend の HTML view を表示。
         JA/EN は i18n.language で path を出し分け。 */}
      {docModal && (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => setDocModal(null)}
        >
          <div
            className="bg-white dark:bg-gray-800 w-full max-w-4xl h-[85vh] rounded-lg shadow-xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700">
              <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {docModal === 'privacy'
                  ? (t('onboarding.consent.view_privacy') || 'プライバシーポリシー')
                  : (t('onboarding.consent.view_terms') || '利用規約')}
              </div>
              <button
                type="button"
                onClick={() => setDocModal(null)}
                className="text-sm px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200"
              >
                ✕
              </button>
            </div>
            <iframe
              title={docModal}
              src={`${(i18n.language as string)?.startsWith('en') ? '/en' : ''}/${docModal}`}
              className="flex-1 w-full bg-white"
            />
          </div>
        </div>
      )}
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
          {required ? <span className="ml-2 text-red-600 text-xs">契約履行（必須）</span> : null}
        </div>
        <p className="mt-1 text-xs text-gray-600 dark:text-gray-300">{description}</p>
      </div>
    </label>
  )
}
