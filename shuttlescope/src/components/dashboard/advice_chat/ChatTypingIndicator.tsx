/**
 * ChatTypingIndicator — 「AI が考え中」の 3 点バウンスインジケーター。
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
        className="shrink-0 w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center"
        aria-hidden="true"
      >
        <MIcon name="auto_awesome" size={14} fill={1} className="text-white" ariaHidden />
      </div>
      <div className="rounded-2xl rounded-tl-sm px-3 py-2.5 bg-gray-100 dark:bg-gray-700">
        <div className="flex gap-1 items-end h-3" aria-hidden="true">
          <span className="chat-typing-dot" style={{ animationDelay: '0s' }} />
          <span className="chat-typing-dot" style={{ animationDelay: '0.15s' }} />
          <span className="chat-typing-dot" style={{ animationDelay: '0.3s' }} />
        </div>
      </div>
    </div>
  )
}
