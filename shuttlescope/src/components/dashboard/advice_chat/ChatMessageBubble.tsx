/**
 * ChatMessageBubble — 1 メッセージのバブル表示。
 *
 * - user / ai / system を判別し、左右配置・色・尻尾形状を切替。
 * - showAvatar=true のときのみアバター描画 (連続同 author の最初だけ)。
 * - 新着 AI メッセージは typewriter で 1 文字ずつ表示する。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { ChatMessage } from './useAdviceChat'
import { useTypewriter } from './useTypewriter'

interface Props {
  msg: ChatMessage
  showAvatar: boolean
  isAdmin: boolean
  /** ユーザ画面表示名 (User メッセージ avatar 初期文字用). */
  userDisplayName: string | null
  /** true ならこのメッセージは新着 → typewriter する。AI メッセージのみ尊重。 */
  typewrite: boolean
  /** typewriter 終了時に呼ぶ (newMessageIds から外す)。 */
  onTypewriterDone?: (id: ChatMessage['id']) => void
}

export function ChatMessageBubble({
  msg,
  showAvatar,
  isAdmin,
  userDisplayName,
  typewrite,
  onTypewriterDone,
}: Props) {
  const { t } = useTranslation()
  const isUser = msg.author === 'user'
  const [hovered, setHovered] = useState(false)

  const conf =
    typeof msg.confidence === 'number' && isFinite(msg.confidence)
      ? Math.round(msg.confidence * 100)
      : null

  // ── AI 用 typewriter ──
  const { revealed, isTyping } = useTypewriter(
    !isUser ? msg.content : '',
    25,
    !isUser && typewrite && !msg._pending,
  )
  // 完了通知
  if (!isUser && typewrite && !isTyping && revealed === msg.content && onTypewriterDone) {
    // 副作用は render 内で発火しないよう microtask に逃がす
    queueMicrotask(() => onTypewriterDone(msg.id))
  }

  const renderedContent = isUser ? msg.content : revealed
  const timestamp = msg.created_at ? new Date(msg.created_at) : null
  const tsText = timestamp
    ? `${String(timestamp.getHours()).padStart(2, '0')}:${String(timestamp.getMinutes()).padStart(2, '0')}`
    : ''

  // ── Avatar ──
  const avatar = showAvatar ? (
    isUser ? (
      <div
        className="shrink-0 w-6 h-6 rounded-full bg-blue-200 dark:bg-blue-900 text-blue-900 dark:text-blue-100 flex items-center justify-center text-[11px] font-semibold"
        aria-hidden="true"
      >
        {(userDisplayName ?? t('auto.AdviceChat.you'))[0] ?? 'U'}
      </div>
    ) : (
      <div
        className="shrink-0 w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center"
        aria-hidden="true"
      >
        <MIcon name="auto_awesome" size={14} fill={1} className="text-white" ariaHidden />
      </div>
    )
  ) : (
    <div className="shrink-0 w-6 h-6" aria-hidden="true" />
  )

  if (isUser) {
    return (
      <div
        className="chat-bubble-enter flex items-end justify-end gap-2"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div className="flex flex-col items-end max-w-[75%]">
          <div
            className={`rounded-2xl rounded-tr-sm px-3 py-2 text-sm leading-relaxed bg-blue-600 text-white ${
              msg._pending ? 'opacity-70' : ''
            }`}
          >
            <div className="whitespace-pre-wrap break-words">{renderedContent}</div>
          </div>
          {(msg.date_from || msg.date_to) && (
            <div
              className="mt-1 inline-flex items-center gap-1 text-[10px] bg-indigo-100 dark:bg-indigo-900/50 text-indigo-900 dark:text-indigo-100 px-1.5 py-0.5 rounded-full"
              aria-label={t('auto.AdviceChat.period.chipLabel')}
            >
              <MIcon name="event" size={11} ariaHidden />
              <span>
                {(msg.date_from ?? '…')} → {(msg.date_to ?? t('auto.AdviceChat.period.today'))}
              </span>
            </div>
          )}
          {hovered && tsText && (
            <div className="text-[10px] text-gray-500 mt-0.5">{tsText}</div>
          )}
        </div>
        {avatar}
      </div>
    )
  }

  // ── AI / system bubble ──
  return (
    <div
      className="chat-bubble-enter flex items-end justify-start gap-2"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {avatar}
      <div className="flex flex-col items-start max-w-[85%]">
        <div className="rounded-2xl rounded-tl-sm px-3 py-2 text-sm leading-relaxed bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100">
          <div className="whitespace-pre-wrap break-words">
            {renderedContent}
            {isTyping && (
              <span className="chat-cursor-blink inline-block w-[1px] h-[1em] align-text-bottom ml-[1px] bg-gray-500" />
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 mt-1 flex-wrap">
          {conf != null && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-200">
              {t('auto.AdviceChat.confidence', { n: conf })}
            </span>
          )}
          {msg.is_fallback && isAdmin && (
            <span
              title={t('auto.AdviceChat.safety_hint_admin')}
              aria-label={t('auto.AdviceChat.safety_hint_admin')}
              className="inline-flex items-center text-[10px] text-amber-700 dark:text-amber-300"
            >
              <MIcon name="shield" size={12} ariaHidden />
            </span>
          )}
          {msg.evidence_path && (
            <a
              href={msg.evidence_path}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-blue-600 dark:text-blue-300 hover:underline"
            >
              {t('auto.AdviceChat.view_details')}
            </a>
          )}
          {hovered && tsText && (
            <span className="text-[10px] text-gray-500">{tsText}</span>
          )}
        </div>
      </div>
    </div>
  )
}
