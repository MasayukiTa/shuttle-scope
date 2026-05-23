/**
 * AdviceChatPanel — Growth Advisor (β) チャット UI (MVP / 最小機能版)。
 *
 * - role: coach / analyst / admin のみ表示 (Page 側で gate するが本体でも null guard)。
 * - 後続スライスで typewriter / fade / sticky / gradient 等の polish を追加予定。
 * - i18n: 全ての表示文字列は auto.AdviceChat.* キー。
 */
import { KeyboardEvent, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { useCardTheme } from '@/hooks/useCardTheme'
import { useAuth } from '@/hooks/useAuth'
import { useDemoModeStore } from '@/store/demoModeStore'
import { useAdviceChat, ChatMessage } from './useAdviceChat'

const ALLOWED_ROLES = new Set(['coach', 'analyst', 'admin'])

function MessageBubble({ msg, t }: { msg: ChatMessage; t: (k: string, o?: Record<string, unknown>) => string }) {
  const isUser = msg.author === 'user'
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div
          className={`max-w-[80%] rounded-2xl rounded-br-sm px-3 py-2 text-sm leading-relaxed bg-blue-600 text-white ${msg._pending ? 'opacity-70' : ''}`}
        >
          <div className="whitespace-pre-wrap break-words">{msg.content}</div>
        </div>
      </div>
    )
  }
  // AI / system bubble
  const conf =
    typeof msg.confidence === 'number' && isFinite(msg.confidence)
      ? Math.round(msg.confidence * 100)
      : null
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-sm px-3 py-2 text-sm leading-relaxed bg-gray-100 text-gray-900 dark:bg-gray-700 dark:text-gray-100">
        <div className="whitespace-pre-wrap break-words">{msg.content}</div>
        {conf != null && (
          <div className="mt-1 text-[10px] opacity-70">
            {t('auto.AdviceChat.confidence', { n: conf })}
          </div>
        )}
      </div>
    </div>
  )
}

export function AdviceChatPanel() {
  const { t } = useTranslation()
  const { role } = useAuth()
  const { card, textHeading, textMuted } = useCardTheme()
  const demoActive = useDemoModeStore((s) => s.active)

  const {
    messages,
    isInitializing,
    isSending,
    error,
    sendMessage,
    resetSession,
  } = useAdviceChat()

  const [draft, setDraft] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // textarea auto-resize (max 5 行)
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const lineHeight = 20 // ~ text-sm leading-relaxed
    const maxHeight = lineHeight * 5 + 16 // padding 込み
    ta.style.height = `${Math.min(ta.scrollHeight, maxHeight)}px`
  }, [draft])

  // 新規メッセージで一番下まで scroll
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, isSending])

  if (!role || !ALLOWED_ROLES.has(role)) {
    return null
  }

  const handleSubmit = async () => {
    const text = draft.trim()
    if (!text || isSending) return
    setDraft('')
    await sendMessage(text)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void handleSubmit()
    }
  }

  const onReset = async () => {
    if (messages.length === 0) {
      await resetSession()
      return
    }
    if (typeof window !== 'undefined' && !window.confirm(t('auto.AdviceChat.reset_confirm'))) {
      return
    }
    await resetSession()
  }

  return (
    <div className={`${card} rounded-xl border shadow-sm p-4 space-y-3`}>
      {/* ── Header ────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <MIcon name="auto_awesome" size={20} fill={1} className="text-blue-600 dark:text-blue-300 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h2 className={`text-sm font-semibold ${textHeading}`}>
              {t('auto.AdviceChat.title')}
            </h2>
            <p className={`text-xs ${textMuted} truncate`}>
              {t('auto.AdviceChat.subtitle')}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {demoActive && (
            <span className="inline-flex items-center px-2 py-0.5 text-[10px] rounded bg-amber-500 text-white">
              {t('auto.AdviceChat.demo_chip')}
            </span>
          )}
          <button
            type="button"
            onClick={onReset}
            aria-label={t('auto.AdviceChat.reset')}
            title={t('auto.AdviceChat.reset')}
            className="inline-flex items-center justify-center w-8 h-8 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200"
            disabled={isSending}
          >
            <MIcon name="refresh" size={18} ariaHidden />
          </button>
        </div>
      </div>

      {/* ── Messages ──────────────────────────────────────── */}
      <div
        ref={scrollRef}
        aria-live="polite"
        className="max-h-[480px] min-h-[160px] overflow-y-auto space-y-2 px-1 py-2 rounded bg-gray-50 dark:bg-gray-900/40"
      >
        {isInitializing && (
          <div className={`text-center text-xs ${textMuted}`}>...</div>
        )}
        {!isInitializing && messages.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
            <MIcon name="auto_awesome" size={28} className={`${textMuted} opacity-40`} ariaHidden />
            <div className={`text-xs ${textMuted}`}>
              {t('auto.AdviceChat.empty_state')}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} msg={m} t={t} />
        ))}
        {isSending && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-sm px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-300">
              …
            </div>
          </div>
        )}
      </div>

      {/* ── Composer ──────────────────────────────────────── */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={t('auto.AdviceChat.placeholder')}
          disabled={isSending}
          className="flex-1 resize-none rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-sm leading-relaxed text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSending || draft.trim().length === 0}
          aria-label={t('auto.AdviceChat.send')}
          className="inline-flex items-center justify-center px-3 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <MIcon name="send" size={18} ariaHidden />
        </button>
      </div>

      {/* ── Error ─────────────────────────────────────────── */}
      {error && (
        <div className="flex items-start justify-between gap-2 text-xs rounded border border-red-300 bg-red-50 dark:bg-red-900/30 px-3 py-2 text-red-700 dark:text-red-200">
          <span className="break-words">{t(error)}</span>
        </div>
      )}
    </div>
  )
}
