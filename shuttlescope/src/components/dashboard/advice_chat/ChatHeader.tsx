/**
 * ChatHeader — Growth Advisor のグラデーションヘッダ。
 * indigo→purple→pink のミュートしたグラデーションで「会話 UI」感を出す。
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
    <div className="relative rounded-t-xl bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-opacity-90 px-3 py-3 md:px-4 md:py-3 text-white">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <span className="inline-flex items-center justify-center w-9 h-9 rounded-full bg-white/15 shrink-0 shadow-inner">
            <MIcon
              name="auto_awesome"
              size={20}
              fill={1}
              className="text-white drop-shadow"
              ariaHidden
            />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold leading-tight text-white">
              {t('auto.AdviceChat.title')}
            </h2>
            <p className="text-[11px] text-white/85 truncate">
              {t('auto.AdviceChat.subtitle')}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {demoActive && (
            <span className="inline-flex items-center px-2 py-0.5 text-[10px] rounded bg-amber-400 text-amber-950 font-semibold">
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
              className="inline-flex items-center justify-center w-8 h-8 rounded-full hover:bg-white/15 text-white"
            >
              <MIcon name="help" size={18} ariaHidden />
            </button>
            {helpOpen && (
              <div
                role="tooltip"
                className="absolute right-0 top-9 z-10 w-56 rounded bg-gray-900 text-white text-[11px] px-2 py-1.5 shadow-lg"
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
            className="inline-flex items-center justify-center w-8 h-8 rounded-full hover:bg-white/15 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <MIcon name="refresh" size={18} ariaHidden />
          </button>
        </div>
      </div>
    </div>
  )
}
