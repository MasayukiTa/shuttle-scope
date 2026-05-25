/**
 * ChatHeader — Growth Advisor のヘッダー。
 *
 * 2026-05-25 redesign: 旧版は indigo→purple→pink グラデーション + 派手な
 *   typewriter / bounce / bubble-enter で「Tailwind の悪い例」だったため、
 *   solid な slate ベースに統一して落ち着いた業務UI に置き換え。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  demoActive: boolean
  isSending: boolean
  onResetClick: () => void
}

export function ChatHeader({ demoActive, isSending, onResetClick }: Props) {
  const { t } = useTranslation()
  const [helpOpen, setHelpOpen] = useState(false)

  return (
    <div className="rounded-t-xl border-b border-slate-200 bg-slate-50 px-3 py-3 md:px-4 md:py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <span className="inline-flex items-center justify-center w-9 h-9 rounded-full bg-slate-200 shrink-0">
            <MIcon
              name="forum"
              size={20}
              className="text-slate-700"
              ariaHidden
            />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold leading-tight text-slate-900">
              {t('auto.AdviceChat.title')}
            </h2>
            <p className="text-[11px] text-slate-600 truncate">
              {t('auto.AdviceChat.subtitle')}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {demoActive && (
            <span className="inline-flex items-center px-2 py-0.5 text-[10px] rounded bg-amber-100 text-amber-900 border border-amber-200 font-medium">
              {t('auto.AdviceChat.demo_chip')}
            </span>
          )}
          <div className="relative">
            <button
              type="button"
              onClick={() => setHelpOpen((v) => !v)}
              onBlur={() => setHelpOpen(false)}
              aria-label={t('auto.AdviceChat.help_tooltip')}
              title={t('auto.AdviceChat.help_tooltip')}
              className="inline-flex items-center justify-center w-8 h-8 rounded text-slate-600 hover:bg-slate-200"
            >
              <MIcon name="help" size={18} ariaHidden />
            </button>
            {helpOpen && (
              <div
                role="tooltip"
                className="absolute right-0 top-9 z-10 w-56 rounded bg-slate-900 text-white text-[11px] px-2 py-1.5 shadow-lg"
              >
                {t('auto.AdviceChat.help_tooltip')}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onResetClick}
            aria-label={t('auto.AdviceChat.reset')}
            title={t('auto.AdviceChat.reset')}
            disabled={isSending}
            className="inline-flex items-center justify-center w-8 h-8 rounded text-slate-600 hover:bg-slate-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <MIcon name="refresh" size={18} ariaHidden />
          </button>
        </div>
      </div>
    </div>
  )
}
