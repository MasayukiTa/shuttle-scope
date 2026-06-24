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
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-5 py-8">
        <div className="flex items-center gap-3 mb-2">
          <MIcon name="menu_book" size={26} className="text-blue-500" />
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
            {t('getting_started.title')}
          </h1>
        </div>
        <p className="text-gray-600 dark:text-gray-300 leading-relaxed mb-6">
          {t('getting_started.intro')}
        </p>

        {!canSetup && (
          <div className="mb-6 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 px-4 py-3 text-sm text-amber-900 dark:text-amber-100 flex gap-2">
            <MIcon name="info" size={18} className="shrink-0 mt-0.5" />
            <span>{t('getting_started.role_note')}</span>
          </div>
        )}

        <ol className="space-y-4">
          {steps.map((s, i) => (
            <li
              key={s.title}
              className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4"
            >
              <div className="flex items-start gap-3">
                <div className="shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <MIcon name={s.iconName} size={18} className="text-blue-500" />
                    <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                      {s.title}
                    </h2>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed mb-3">
                    {s.body}
                  </p>
                  <button
                    onClick={() => navigate(s.to)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-sm"
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
            className="text-sm text-blue-500 hover:text-blue-400"
          >
            {t('getting_started.back_to_matches')}
          </button>
        </div>
      </div>
    </div>
  )
}
