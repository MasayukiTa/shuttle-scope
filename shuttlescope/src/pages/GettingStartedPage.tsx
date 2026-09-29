import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { useAuth } from '@/hooks/useAuth'

/**
 * はじめに / Getting Started。
 *
 * セットアップ系チュートリアル（チーム/選手 → 試合作成 → 動画読込&アノテート →
 * 解析閲覧）の導線が無いという beta ユーザーのフィードバックに対応する案内ページ。
 * presentational のみ（API 変更なし）。文言は全て i18n（ja/en）。
 */
export function GettingStartedPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { role } = useAuth()

  // セットアップ（選手・試合作成）は analyst / admin のみ可能。
  const canSetup = role === 'analyst' || role === 'admin'

  const steps = useMemo(
    () => [
      {
        iconName: 'group',
        title: t('getting_started.step1_title'),
        body: t('getting_started.step1_body'),
        cta: t('getting_started.step1_cta'),
        to: '/settings',
      },
      {
        iconName: 'sports_tennis',
        title: t('getting_started.step2_title'),
        body: t('getting_started.step2_body'),
        cta: t('getting_started.step2_cta'),
        to: '/matches',
      },
      {
        iconName: 'movie',
        title: t('getting_started.step3_title'),
        body: t('getting_started.step3_body'),
        cta: t('getting_started.step3_cta'),
        to: '/matches',
      },
      {
        iconName: 'bar_chart',
        title: t('getting_started.step4_title'),
        body: t('getting_started.step4_body'),
        cta: t('getting_started.step4_cta'),
        to: '/dashboard',
      },
    ],
    [t],
  )

  return (
    <div className="h-full overflow-y-auto bg-[var(--ss-bg-app)]">
      <div className="max-w-3xl mx-auto px-5 py-8">
        <div className="flex items-center gap-3 mb-2">
          <MIcon name="menu_book" size={26} className="text-[var(--ss-brand)]" />
          <h1 className="text-2xl font-semibold tracking-[-0.014em] text-[var(--ss-t1)]">
            {t('getting_started.title')}
          </h1>
        </div>
        <p className="text-[var(--ss-t2)] leading-relaxed mb-6">
          {t('getting_started.intro')}
        </p>

        {!canSetup && (
          <div className="mb-6 rounded-ss-md border border-[var(--ss-warning-border)] bg-[var(--ss-warning-bg)] px-4 py-3 text-sm text-[var(--ss-warning-text)] flex gap-2">
            <MIcon name="info" size={18} className="shrink-0 mt-0.5" />
            <span>{t('getting_started.role_note')}</span>
          </div>
        )}

        <ol className="space-y-4">
          {steps.map((s, i) => (
            <li
              key={s.title}
              className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] shadow-card p-4"
            >
              <div className="flex items-start gap-3">
                <div className="shrink-0 w-8 h-8 rounded-ss-pill bg-[var(--ss-brand)] text-white flex items-center justify-center text-sm font-semibold ss-num">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <MIcon name={s.iconName} size={18} className="text-[var(--ss-brand)]" />
                    <h2 className="text-base font-semibold text-[var(--ss-t1)]">
                      {s.title}
                    </h2>
                  </div>
                  <p className="text-sm text-[var(--ss-t2)] leading-relaxed mb-3">
                    {s.body}
                  </p>
                  <button
                    onClick={() => navigate(s.to)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white rounded-ss-md text-sm transition-colors duration-fast ease-out"
                  >
                    {s.cta}
                    <MIcon name="arrow_forward" size={14} />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-8 text-center">
          <button
            onClick={() => navigate('/matches')}
            className="text-sm text-[var(--ss-brand)] hover:text-[var(--ss-brand-hover)]"
          >
            {t('getting_started.back_to_matches')}
          </button>
        </div>
      </div>
    </div>
  )
}
