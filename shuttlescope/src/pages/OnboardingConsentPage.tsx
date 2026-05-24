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
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ConsentRecord,
  ConsentStateDTO,
  ConsentType,
  getMyConsents,
  submitConsents,
} from '@/api/client'
import { MIcon } from '@/components/common/MIcon'

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
  // 文書 popup. null = 閉、各 slug = 表示中。
  // privacy / terms は必須同意の読了対象、それ以外は「その他の規約」リンクから開かれる。
  type DocSlug = 'privacy' | 'terms' | 'license' | 'data_contribution' | 'dpa_template' | 'beta_agreement' | 'ai_training' | 'research' | 'body_analyst' | 'body_coach'
  const [docModal, setDocModal] = useState<null | DocSlug>(null)
  // 「その他の規約」一覧 overlay の表示状態
  const [otherDocsOpen, setOtherDocsOpen] = useState<boolean>(false)
  // 各文書を最後までスクロールしたか。両方 true にしないと必須チェックを許可しない。
  // (典型的な法務同意 UI パターン: 「読んだ」を擬制するための強制スクロール)
  const [scrolledPrivacy, setScrolledPrivacy] = useState(false)
  const [scrolledTerms, setScrolledTerms] = useState(false)
  const bothDocsScrolled = scrolledPrivacy && scrolledTerms

  // 同意/確認状態。initial は false、ユーザが明示的にチェックしない限り送信されない。
  const [given, setGiven] = useState<Record<ConsentType, boolean>>({
    // 必須 (契約履行) — ユーザに明示 check させるため initial=false。
    service_delivery: false,
    beta_agreement: false,
    // 任意同意 — β期間 opt-out モデル: initial=true。
    // ユーザは見て自分でチェックを外せばその場で「同意しない」記録になる。
    // (利用には影響しない設計)
    ai_training: true,
    research_participation: true,
    // cross_border_transfer は UI に出さないが backend 側の互換のため keep。
    // EU-Japan 十分性認定済みなので default=true でも問題なし。
    cross_border_transfer: true,
    // 体組成データの開示: β期間 default ON。
    body_disclose_to_analyst: true,
    body_disclose_to_coach: true,
  })

  useEffect(() => {
    let cancelled = false
    getMyConsents()
      .then((r) => {
        if (cancelled) return
        setState(r.data)
        // PRIVACY §9ter: 未成年は AI 学習チェックを default off に倒す
        if (r.data?.viewer_is_minor) {
          setGiven((g) => ({ ...g, ai_training: false }))
        }
        // 既存 consent record の反映ポリシー:
        //   - 現行 terms_version ('1.3' 等) の record のみ尊重する。
        //   - 旧 version の record は文書改定で stale になっているため
        //     opt-out default (= initial true) に戻す。
        //   - ユーザが現行版で意図的に外した record (consent_given=false) は
        //     そのまま尊重 (GDPR Article 7(3) withdraw)。
        const currentTerms = r.data.current_versions?.terms
        const existing: Record<string, ConsentRecord> = {}
        for (const c of r.data.consents) {
          if (!currentTerms || c.terms_version === currentTerms) {
            existing[c.consent_type] = c
          }
        }
        setGiven((prev) => {
          const next = { ...prev }
          for (const t of OPTIONAL) {
            const rec = existing[t]
            if (rec) {
              next[t] = !!rec.consent_given
            }
            // rec 無し / stale 版のみ → initial (opt-out true) を保持
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
              >{t('auto.OnboardingConsentPage.k1')}</button>
              <button
                type="button"
                onClick={() => i18n.changeLanguage('en')}
                className={`px-2 py-1 rounded border ${
                  (i18n.language as string)?.startsWith('en')
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200'
                }`}
              >{t('auto.OnboardingConsentPage.en')}</button>
            </div>
          </div>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
            {t('onboarding.consent.intro') ||
              '本サービス (ShuttleScope) のご利用にあたり、以下の文書をお読みいただき、内容をご確認の上、任意同意項目について同意の可否をご判断ください。'}
          </p>
          {/* 文書表示ボタンは各 checkbox 横に inline で配置するため、
             ヘッダの top 一括ボタンは削除した (UX 集約)。 */}
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

          {/* 必須 checkbox 各々に inline で「文書を読む」ボタンを並置。
             - service_delivery: Privacy + Terms 両方の読了で enable
             - beta_agreement: Terms の読了で enable (= §14 を参照)
             各 docs ボタンは「未読/読了」を色 + check で表示。 */}

          <ConsentCheckbox
            checked={given.service_delivery}
            onChange={(v) => setGiven((g) => ({ ...g, service_delivery: v }))}
            label={t('onboarding.consent.service_delivery_label') || 'Privacy Notice および Terms of Service の内容を確認しました'}
            description={
              t('onboarding.consent.service_delivery_desc') ||
              'これらの文書に記載されたデータ処理（試合データ・選手プロフィール・解析結果の処理、認証、監査ログ等）は本サービス提供に必要な処理であり、GDPR Article 6(1)(b) および APPI 第18条に基づき行われます。これらの処理を停止する場合はサービスの利用終了をお選びください。'
            }
            required
            requiredMarker={t('onboarding.consent.required_marker') || '契約履行（必須）'}
            disabled={!bothDocsScrolled}
            docButtons={
              <div className="mt-2 flex flex-wrap gap-2">
                <DocButton
                  onClick={() => setDocModal('privacy')}
                  scrolled={scrolledPrivacy}
                  label={`${t('onboarding.consent.view_privacy') || 'プライバシーポリシーを表示'} (v${ppv})`}
                  doneLabel={t('onboarding.consent.read_done') || '読了'}
                />
                <DocButton
                  onClick={() => setDocModal('terms')}
                  scrolled={scrolledTerms}
                  label={`${t('onboarding.consent.view_terms') || '利用規約を表示'} (v${tv})`}
                  doneLabel={t('onboarding.consent.read_done') || '読了'}
                />
              </div>
            }
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
            requiredMarker={t('onboarding.consent.required_marker') || '契約履行（必須）'}
            disabled={!bothDocsScrolled}
            docButtons={
              <div className="mt-2 flex flex-wrap gap-2">
                <DocButton
                  onClick={() => setDocModal('terms')}
                  scrolled={scrolledTerms}
                  label={`${t('onboarding.consent.view_terms') || '利用規約を表示'} (v${tv})`}
                  doneLabel={t('onboarding.consent.read_done') || '読了'}
                />
              </div>
            }
          />
        </section>

        <section className="space-y-4 border-t border-gray-200 dark:border-gray-700 pt-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('onboarding.consent.optional_section') || '任意同意事項（チェックしなくても本サービスは使えます）'}
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {t('onboarding.consent.optional_hint') ||
              '以下の任意同意は GDPR Article 6(1)(a) / APPI に基づく同意です。撤回はお問い合わせフォームまたは contact@shuttle-scope.com 宛てメールで受け付けます（受領から 14 日以内に処理）。'}
            {/* 「その他の規約」リンクは任意同意 hint 文の末尾にひっそり配置 (= スマホでも
               独立行にならず文中の青リンクとして目立ちすぎない)。 */}
            {' '}
            <button
              type="button"
              onClick={() => setOtherDocsOpen(true)}
              className="underline text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300"
            >
              {t('onboarding.consent.other_docs_link') || 'その他の規約はこちら'}
            </button>
          </p>

          <ConsentCheckbox
            checked={given.ai_training}
            onChange={(v) => setGiven((g) => ({ ...g, ai_training: v }))}
            label={t('onboarding.consent.ai_training_label') || 'AI モデル学習への利用に同意します'}
            description={
              (state.viewer_is_minor
                ? (t('onboarding.consent.ai_training_minor_notice') ||
                   '【未成年の方向け】このチェックは default で外れています。法定代理人とご相談の上、明示的に同意される場合のみチェックを入れてください。 ')
                : '') +
              (t('onboarding.consent.ai_training_desc') ||
              '匿名化・集計化されたデータを将来的なモデル精度向上のために利用します。同意は任意であり、いつでも撤回できます。撤回時は以後の学習対象から除外されます。撤回方法：お問い合わせフォーム（https://shuttle-scope.com/contact）または contact@shuttle-scope.com 宛てメール。')
            }
            docButtons={
              <div className="mt-2 flex flex-wrap gap-2">
                <OptionalDocLink onClick={() => setDocModal('ai_training')} label={t('onboarding.consent.doc_ai_training') || 'AI モデル学習利用規約 (詳細)'} />
              </div>
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
            docButtons={
              <div className="mt-2 flex flex-wrap gap-2">
                <OptionalDocLink onClick={() => setDocModal('research')} label={t('onboarding.consent.doc_research') || '学術研究利用規約 (詳細)'} />
              </div>
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
            docButtons={
              <div className="mt-2 flex flex-wrap gap-2">
                <OptionalDocLink onClick={() => setDocModal('body_analyst')} label={t('onboarding.consent.doc_body_analyst') || '体組成データ アナリスト開示規約 (詳細)'} />
              </div>
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
            docButtons={
              <div className="mt-2 flex flex-wrap gap-2">
                <OptionalDocLink onClick={() => setDocModal('body_coach')} label={t('onboarding.consent.doc_body_coach') || '体組成データ コーチ開示規約 (詳細)'} />
              </div>
            }
          />
        </section>

        {error ? (
          <div className="text-sm text-red-600 dark:text-red-400 border border-red-200 dark:border-red-700/50 rounded p-3">
            {error}
          </div>
        ) : null}

        <footer className="flex flex-col-reverse sm:flex-row gap-3 sm:justify-end pt-4 border-t border-gray-200 dark:border-gray-700">
          {/* 「あとで見るよ」:
             - optionalOnly mode: 常時表示。書き込まず popup 閉じ→次回再 popup
             - 初回 mode: **必須 check 完了後** にのみ表示 (条件付き render)。
               必須未 check の状態で submit を回避する経路を UI から潰す。
               (※ backend 側で別途必須 check も実施しているので二重防御。) */}
          {(optionalOnly || allRequiredChecked) && (
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
              {t('onboarding.consent.later') || '任意項目は後で回答する'}
            </button>
          )}
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

        {/* 同意できない場合の退出経路。
           「同意しないと先に進めない」UI で「ブラウザを閉じる以外の選択肢」を
           ユーザに提示するのは GDPR Art 7(4) (consent freely given) の精神に
           合致する。サイトトップ (apex) かログイン画面のいずれかへ戻れるよう
           にする。 */}
        <footer className="pt-3 mt-2 border-t border-gray-200 dark:border-gray-700 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-gray-500 dark:text-gray-400">
            {t('onboarding.consent.exit_hint') || '同意せずに離れる場合:'}
          </span>
          <div className="flex flex-wrap items-center gap-3">
            <a
              href="https://shuttle-scope.com/"
              className="underline text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100"
            >
              {t('onboarding.consent.back_to_site') || 'shuttle-scope.com に戻る'}
            </a>
            <span aria-hidden="true" className="text-gray-400">{t('auto.OnboardingConsentPage.dot')}</span>
            <button
              type="button"
              onClick={() => {
                // セッションをクリアしてログイン画面に戻す
                try {
                  sessionStorage.removeItem('shuttlescope_token')
                  sessionStorage.removeItem('shuttlescope_refresh_token')
                  sessionStorage.removeItem('shuttlescope_role')
                  sessionStorage.removeItem('shuttlescope_user_id')
                  sessionStorage.removeItem('shuttlescope_display_name')
                  sessionStorage.removeItem('shuttlescope_player_id')
                  sessionStorage.removeItem('shuttlescope_team_name')
                } catch { /* ignore */ }
                // フルリロード (App ルートが /login へ誘導)
                window.location.href = '/#/'
                setTimeout(() => window.location.reload(), 50)
              }}
              className="underline text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-gray-100"
            >
              {t('onboarding.consent.back_to_login') || 'ログイン画面に戻る'}
            </button>
          </div>
        </footer>
      </div>

      {/* 「その他の規約」一覧 overlay — LICENSE / DATA_CONTRIBUTION / DPA / β契約書。
         クリックで DocModal を開いて iframe 表示。必須同意とは紐付かない。 */}
      {otherDocsOpen && (
        <div
          className="fixed inset-0 z-[210] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => setOtherDocsOpen(false)}
        >
          <div
            className="bg-white dark:bg-gray-800 w-full max-w-md rounded-lg shadow-xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700">
              <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {t('onboarding.consent.other_docs_title') || 'その他の規約・契約書類'}
              </div>
              <button
                type="button"
                onClick={() => setOtherDocsOpen(false)}
                className="text-sm px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200"
              >
                <MIcon name="close" size={14} />
              </button>
            </div>
            <div className="p-3 space-y-2">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {t('onboarding.consent.other_docs_hint') ||
                  '同意必須ではありませんが、利用目的に応じて参照できる文書です。'}
              </p>
              {([
                { slug: 'beta_agreement' as DocSlug, label: t('onboarding.consent.doc_beta') || 'β期間データ取り扱い同意書 (公開版)' },
                { slug: 'dpa_template' as DocSlug, label: t('onboarding.consent.doc_dpa') || 'Data Processing Agreement テンプレート (GDPR Art 28)' },
                { slug: 'data_contribution' as DocSlug, label: t('onboarding.consent.doc_dct') || 'データ提供規約' },
                { slug: 'license' as DocSlug, label: t('onboarding.consent.doc_license') || 'ソフトウェアライセンス' },
              ]).map(({ slug, label }) => (
                <button
                  key={slug}
                  type="button"
                  onClick={() => { setOtherDocsOpen(false); setDocModal(slug) }}
                  className="w-full text-left text-sm px-3 py-2 rounded border border-gray-200 dark:border-gray-700 hover:bg-blue-50 dark:hover:bg-blue-900/30 text-gray-900 dark:text-gray-100 inline-flex items-center gap-2"
                >
                  <MIcon name="visibility" size={14} />
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 文書 popup modal. iframe で backend の HTML view を表示。
         JA/EN は i18n.language で path を出し分け。
         - 最下部までスクロールすると scrolled[doc]=True にする (典型的な法務同意 UI)。
         - 「印刷」ボタンで iframe.contentWindow.print()。 */}
      {docModal && (
        <DocModal
          docKind={docModal}
          lang={(i18n.language as string)?.startsWith('en') ? 'en' : 'ja'}
          onClose={() => setDocModal(null)}
          onReachedBottom={() => {
            // 必須読了対象 (privacy / terms) のみ scroll flag を立てる。
            // その他の規約 (license / dpa / β etc) はスクロール完了しても
            // 必須 checkbox の解放には影響させない (任意参照のため)。
            if (docModal === 'privacy') setScrolledPrivacy(true)
            else if (docModal === 'terms') setScrolledTerms(true)
          }}
          alreadyScrolled={
            docModal === 'privacy' ? scrolledPrivacy :
            docModal === 'terms' ? scrolledTerms : false
          }
          t={t}
        />
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
  requiredMarker,
  disabled,
  docButtons,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  description: string
  required?: boolean
  // i18n-resolved label for the red "必須" badge. Passed in so this component
  // does not need its own useTranslation hook.
  requiredMarker?: string
  disabled?: boolean
  docButtons?: React.ReactNode
}) {
  return (
    <label
      className={`flex items-start gap-3 p-3 rounded border ${
        disabled
          ? 'border-gray-200 dark:border-gray-700 opacity-90 cursor-not-allowed bg-gray-50/40 dark:bg-gray-800/30'
          : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer'
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1 h-5 w-5 text-blue-600 rounded disabled:cursor-not-allowed"
      />
      <div className="flex-1">
        <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
          {label}
          {required ? <span className="ml-2 text-red-600 text-xs">{requiredMarker}</span> : null}
        </div>
        <p className="mt-1 text-xs text-gray-600 dark:text-gray-300">{description}</p>
        {docButtons}
      </div>
    </label>
  )
}

/**
 * 関連文書 modal を開くボタン。読了 (scrolled) なら緑 ✓、未読なら青で目立たせる。
 * label に渡された文字列を表示。
 */
function DocButton({
  onClick, scrolled, label, doneLabel,
}: {
  onClick: () => void
  scrolled: boolean
  label: string
  doneLabel: string
}) {
  return (
    <button
      type="button"
      // 親 <label> の click が transmit して checkbox を toggle しないよう block。
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick() }}
      className={`text-xs px-2.5 py-1 rounded border inline-flex items-center gap-1 ${
        scrolled
          ? 'border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
          : 'border-blue-400 dark:border-blue-600 bg-white dark:bg-gray-800 text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30 animate-pulse-slow'
      }`}
    >
      {/* CLAUDE.md / memory: アイコンは絶対 Google Material Symbols (MIcon) を使う。
         emoji や lucide は使わない。subset CSS 経由でロードされる icon のみ表示可。 */}
      <MIcon name={scrolled ? 'check' : 'visibility'} size={14} />
      {label}
      {scrolled && <span className="ml-1 text-[10px] opacity-80">({doneLabel})</span>}
    </button>
  )
}

/**
 * 任意同意項目の補足規約への中立 link button。読了強制はしないので scroll 追跡なし。
 */
function OptionalDocLink({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick() }}
      className="text-xs px-2.5 py-1 rounded border inline-flex items-center gap-1 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
    >
      <MIcon name="description" size={14} />
      {label}
    </button>
  )
}

// 現在 path から header に出す文書名を解決する。クロスリンクで navigate した
// 先 (license / data_contribution 等) も初期 doc と同じくらい綺麗に表示するため。
type DocKindAll = 'privacy' | 'terms' | 'license' | 'data_contribution' | 'dpa_template' | 'beta_agreement' | 'ai_training' | 'research' | 'body_analyst' | 'body_coach'
function _titleForPath(path: string, fallbackKind: DocKindAll, t: (k: string) => string): string {
  const norm = (path || '').replace(/^\/en/, '')
  if (norm.includes('/legal/privacy')) return t('onboarding.consent.view_privacy') || 'プライバシーポリシー'
  if (norm.includes('/legal/terms')) return t('onboarding.consent.view_terms') || '利用規約'
  if (norm.includes('/legal/license')) return t('onboarding.consent.doc_license') || 'ソフトウェアライセンス'
  if (norm.includes('/legal/data_contribution')) return t('onboarding.consent.doc_dct') || 'データ提供規約'
  if (norm.includes('/legal/dpa_template')) return t('onboarding.consent.doc_dpa') || 'Data Processing Agreement'
  if (norm.includes('/legal/beta_agreement')) return t('onboarding.consent.doc_beta') || 'β期間データ取り扱い同意書'
  if (norm.includes('/legal/ai_training')) return t('onboarding.consent.doc_ai_training') || 'AI モデル学習利用規約 (詳細)'
  if (norm.includes('/legal/research')) return t('onboarding.consent.doc_research') || '学術研究利用規約 (詳細)'
  if (norm.includes('/legal/body_analyst')) return t('onboarding.consent.doc_body_analyst') || '体組成データ アナリスト開示規約 (詳細)'
  if (norm.includes('/legal/body_coach')) return t('onboarding.consent.doc_body_coach') || '体組成データ コーチ開示規約 (詳細)'
  // fallback: 初期 docKind から
  const fb: Record<DocKindAll, string> = {
    privacy: t('onboarding.consent.view_privacy') || 'プライバシーポリシー',
    terms: t('onboarding.consent.view_terms') || '利用規約',
    license: t('onboarding.consent.doc_license') || 'ソフトウェアライセンス',
    data_contribution: t('onboarding.consent.doc_dct') || 'データ提供規約',
    dpa_template: t('onboarding.consent.doc_dpa') || 'Data Processing Agreement',
    beta_agreement: t('onboarding.consent.doc_beta') || 'β期間データ取り扱い同意書',
    ai_training: t('onboarding.consent.doc_ai_training') || 'AI モデル学習利用規約 (詳細)',
    research: t('onboarding.consent.doc_research') || '学術研究利用規約 (詳細)',
    body_analyst: t('onboarding.consent.doc_body_analyst') || '体組成データ アナリスト開示規約 (詳細)',
    body_coach: t('onboarding.consent.doc_body_coach') || '体組成データ コーチ開示規約 (詳細)',
  }
  return fb[fallbackKind]
}

// 文書 popup modal: 利用規約 / プライバシーポリシー の HTML を iframe で表示。
// scroll を最下部まで到達したら onReachedBottom() を call、parent は scrolled flag を立てる。
// 印刷ボタンで iframe.contentWindow.print()。
function DocModal({
  docKind, lang, onClose, onReachedBottom, alreadyScrolled, t,
}: {
  // privacy / terms は必須同意の読了対象、他は「その他の規約」リンク経由。
  docKind: 'privacy' | 'terms' | 'license' | 'data_contribution' | 'dpa_template' | 'beta_agreement' | 'ai_training' | 'research' | 'body_analyst' | 'body_coach'
  lang: 'ja' | 'en'
  onClose: () => void
  onReachedBottom: () => void
  alreadyScrolled: boolean
  t: (k: string) => string
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const [reached, setReached] = useState<boolean>(alreadyScrolled)
  // 同 modal 内で別 doc に navigate した回数。> 0 で「戻る」ボタンを enable。
  const [visitDepth, setVisitDepth] = useState<number>(0)
  // 現在 iframe が表示している path (header の文書名表示用)
  const [currentPath, setCurrentPath] = useState<string>('')
  // 各 load の reached 状態判定で 1 度目 (= 初期 src 読込) は visitDepth を加算しない
  const isFirstLoadRef = useRef<boolean>(true)

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return
    let cleanup: (() => void) | null = null
    const onLoad = () => {
      try {
        const win = iframe.contentWindow
        const doc = iframe.contentDocument
        if (!win || !doc) return
        // navigate (link click) で再 load されたら visit depth を増やす。
        if (isFirstLoadRef.current) {
          isFirstLoadRef.current = false
        } else {
          setVisitDepth((d) => d + 1)
          // 新規 doc を開いた瞬間は scroll 未到達扱いに戻す。
          setReached(false)
        }
        try { setCurrentPath(win.location.pathname || '') } catch { /* ignore */ }
        const check = () => {
          // 下端に近い (誤差 50px 以内) ら reached 判定
          const scroller = (doc.scrollingElement || doc.documentElement || doc.body) as HTMLElement
          if (!scroller) return
          const remaining = scroller.scrollHeight - (scroller.scrollTop + win.innerHeight)
          if (remaining <= 50) {
            setReached(true)
            // 初期 doc (= 必須同意対象) のみ親 parent 側 scroll flag を立てる。
            // クロスリンクで開いた license/data_contribution は scroll 強制対象外。
            try {
              const path = win.location.pathname || ''
              if (path === `/legal/${docKind}` || path === `/en/legal/${docKind}`) {
                onReachedBottom()
              }
            } catch { /* ignore */ }
          }
        }
        // 初期チェック (短い文書は最初から下端まで見えてる)
        check()
        win.addEventListener('scroll', check, { passive: true })
        cleanup = () => win.removeEventListener('scroll', check)
      } catch {
        // cross-origin の場合は読めない — UI のみ noop
      }
    }
    iframe.addEventListener('load', onLoad)
    return () => {
      iframe.removeEventListener('load', onLoad)
      cleanup?.()
    }
  }, [onReachedBottom, docKind])

  // 戻る: iframe の session history を 1 つ戻す。
  const onBack = () => {
    try {
      iframeRef.current?.contentWindow?.history.back()
      // visitDepth は次の load event で再計測 (= 単純に -1 で良いが本物の history 不一致を避ける)
      setVisitDepth((d) => Math.max(0, d - 1))
    } catch { /* ignore */ }
  }

  const onPrint = () => {
    try {
      iframeRef.current?.contentWindow?.print()
    } catch {
      // ignore
    }
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 w-full max-w-4xl h-[85vh] rounded-lg shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            {/* 戻る: クロスリンクで別 doc に navigate していたら 1 つ前に戻る */}
            <button
              type="button"
              onClick={onBack}
              disabled={visitDepth <= 0}
              title={t('onboarding.consent.back') || '前の文書に戻る'}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <MIcon name="arrow_back" size={18} />
            </button>
            <div className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
              {_titleForPath(currentPath, docKind, t)}
              {reached && (
                <span className="ml-2 inline-flex items-center gap-0.5 text-emerald-600 dark:text-emerald-400 text-xs">
                  <MIcon name="check" size={12} />
                  {t('onboarding.consent.read_done') || '読了'}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={onPrint}
              className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              {t('onboarding.consent.print') || '印刷'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-sm px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200"
            >
              <MIcon name="close" size={14} />
            </button>
          </div>
        </div>
        {/* /legal/privacy /legal/terms はフル版の MD レンダ。
           top page の /privacy /terms (簡易版) ではなく、こちらを popup 表示。 */}
        <iframe
          ref={iframeRef}
          title={docKind}
          src={`${lang === 'en' ? '/en' : ''}/legal/${docKind}`}
          className="flex-1 w-full bg-white"
        />
      </div>
    </div>
  )
}
