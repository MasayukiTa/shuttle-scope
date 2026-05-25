/**
 * ChatTypingIndicator — 「AI 応答待ち」の静的インジケーター。
 *
 * 2026-05-25 redesign: 旧版は 3 点 bounce + gradient avatar。Tailwind の
 *   むにょむにょ系を全廃する方針に従い、静止テキストのみ。
 */
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

export function ChatTypingIndicator() {
  const { t } = useTranslation()
  return (
    <div
      className="flex items-end justify-start gap-2"
      role="status"
      aria-label={t('auto.AdviceChat.bot_name')}
    >
      <div
        className="shrink-0 w-6 h-6 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center"
        aria-hidden="true"
      >
        <MIcon name="forum" size={14} ariaHidden />
      </div>
      <div className="rounded-2xl rounded-tl-sm px-3 py-2 bg-slate-100 text-slate-600 text-xs">
        {t('auto.AdviceChat.bot_name')} …
      </div>
    </div>
  )
}
