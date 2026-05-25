/**
 * AdviceChatPanel — Growth Advisor (β) チャット UI のオーケストレータ。
 *
 * 子コンポーネント:
 *   ChatHeader / ChatMessageBubble / ChatComposer / ChatEmptyState
 *   ChatTypingIndicator / ResetConfirmModal
 *
 * 役割:
 *   - role gate (coach / analyst / admin のみ表示)
 *   - メッセージ map + アバター集約 (連続 author の最初だけアバター描画)
 *   - 新着 AI メッセージの id を newMessageIds に追加し typewriter を発動
 *   - 自動スクロール (新メッセージで一番下まで)
 *   - composer auto-focus / リセット確認モーダル / エラー領域
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import { useDemoModeStore } from '@/store/demoModeStore'
import { useAdviceChat, ChatMessage } from './useAdviceChat'
import { ChatHeader } from './ChatHeader'
import { ChatMessageBubble } from './ChatMessageBubble'
import { ChatComposer, ComposerExtras } from './ChatComposer'
import { ActiveScopeBar } from './ActiveScopeBar'
import { ChatEmptyState } from './ChatEmptyState'
import { ChatTypingIndicator } from './ChatTypingIndicator'
import { ResetConfirmModal } from './ResetConfirmModal'

const ALLOWED_ROLES = new Set(['coach', 'analyst', 'admin'])

interface AdviceChatPanelProps {
  /** ダッシュボードで現在観察中の選手 ID。admin/coach/analyst のときに NIM へ
   *  「ctx.player_id ではなくこの id の analytics を分析せよ」と伝える。
   *  指定しないと従来通り ctx.player_id (=自分) が使われる。 */
  viewedPlayerId?: number | null
}

export function AdviceChatPanel({ viewedPlayerId = null }: AdviceChatPanelProps = {}) {
  const { t } = useTranslation()
  const { role, displayName } = useAuth()
  const demoActive = useDemoModeStore((s) => s.active)

  const {
    messages,
    isInitializing,
    isSending,
    error,
    sendMessage,
    resetSession,
    appliedScope,
  } = useAdviceChat()

  const [draft, setDraft] = useState('')
  const [resetOpen, setResetOpen] = useState(false)
  const [dismissedError, setDismissedError] = useState(false)
  const [newMessageIds, setNewMessageIds] = useState<Set<ChatMessage['id']>>(new Set())

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  /** sendMessage 直後の AI メッセージを検出するための id スナップショット。 */
  const pendingNewRef = useRef<boolean>(false)
  const knownIdsRef = useRef<Set<ChatMessage['id']>>(new Set())

  // 既存メッセージ id のスナップショットを維持。pendingNewRef が立っているとき
  // のみ「新規 AI メッセージ」を newMessageIds に追加する。
  useEffect(() => {
    if (pendingNewRef.current) {
      const newIds: ChatMessage['id'][] = []
      for (const m of messages) {
        if (!knownIdsRef.current.has(m.id) && m.author === 'ai') {
          newIds.push(m.id)
        }
      }
      if (newIds.length > 0) {
        pendingNewRef.current = false
        setNewMessageIds((prev) => {
          const next = new Set(prev)
          for (const id of newIds) next.add(id)
          return next
        })
      }
    }
    const k = new Set<ChatMessage['id']>()
    for (const m of messages) k.add(m.id)
    knownIdsRef.current = k
  }, [messages])

  // 新メッセージ到着でエラー dismiss flag をリセット
  useEffect(() => {
    if (error) setDismissedError(false)
  }, [error])

  // mount で composer に focus
  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  // 新規メッセージで一番下へスクロール
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, isSending])

  const handleSend = useCallback(
    async (extras: ComposerExtras) => {
      const text = draft.trim()
      if (!text || isSending) return
      setDraft('')
      pendingNewRef.current = true
      await sendMessage(text, {
        period: extras.period,
        shotType: extras.shotType,
        zone: extras.zone,
        targetPlayerId: viewedPlayerId,
      })
      textareaRef.current?.focus()
    },
    [draft, isSending, sendMessage, viewedPlayerId],
  )

  const onClearSlot = useCallback(
    (slot: 'period' | 'shot_type' | 'zone') => {
      // 個別スロットクリアを即時反映するため、短い ack メッセージを送る。
      void sendMessage(slot === 'period' ? '全期間で見直して' : 'フィルタを更新', {
        clearSlots: [slot],
        targetPlayerId: viewedPlayerId,
      })
    },
    [sendMessage, viewedPlayerId],
  )
  const onClearAll = useCallback(() => {
    void sendMessage('全部リセット', {
      clearSlots: ['period', 'shot_type', 'zone'],
      targetPlayerId: viewedPlayerId,
    })
  }, [sendMessage, viewedPlayerId])

  const onTypewriterDone = useCallback((id: ChatMessage['id']) => {
    setNewMessageIds((prev) => {
      if (!prev.has(id)) return prev
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }, [])

  // showAvatar = 同じ author の連続シリーズの先頭だけ true
  const avatarFlags = useMemo<boolean[]>(() => {
    const flags: boolean[] = []
    let prevAuthor: string | null = null
    for (const m of messages) {
      flags.push(m.author !== prevAuthor)
      prevAuthor = m.author
    }
    return flags
  }, [messages])

  const isAdmin = role === 'admin'

  if (!role || !ALLOWED_ROLES.has(role)) {
    return null
  }

  const onResetClick = () => {
    if (messages.length === 0) {
      void resetSession()
      return
    }
    setResetOpen(true)
  }
  const onConfirmReset = async () => {
    setResetOpen(false)
    await resetSession()
    setNewMessageIds(new Set())
    textareaRef.current?.focus()
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-sm overflow-hidden flex flex-col w-full">
      {/* ── Header ────────────────────────────────────────── */}
      <ChatHeader demoActive={demoActive} isSending={isSending} onResetClick={onResetClick} />

      {/* ── AI disclaimer (admin-only feature; player-tier opt-in TBD) ── */}
      <div
        role="note"
        className="border-b border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-[11px] leading-relaxed text-amber-900 dark:text-amber-200"
      >
        {t('auto.AdviceChat.disclaimer_banner')}
      </div>

      {/* ── Messages ──────────────────────────────────────── */}
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label={t('auto.AdviceChat.bot_name')}
        className="flex-1 max-h-[480px] min-h-[200px] overflow-y-auto space-y-3 px-2 md:px-4 py-3 bg-gray-50 dark:bg-gray-900/40"
      >
        {isInitializing && (
          <div className="text-center text-xs text-gray-500">…</div>
        )}
        {!isInitializing && messages.length === 0 && !isSending && (
          <ChatEmptyState onPick={(text) => {
            setDraft(text)
            textareaRef.current?.focus()
          }} />
        )}
        {messages.map((m, i) => (
          <ChatMessageBubble
            key={m.id}
            msg={m}
            showAvatar={avatarFlags[i] ?? true}
            isAdmin={isAdmin}
            userDisplayName={displayName}
            typewrite={newMessageIds.has(m.id)}
            onTypewriterDone={onTypewriterDone}
          />
        ))}
        {isSending && <ChatTypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* ── Composer ──────────────────────────────────────── */}
      <div className="border-t border-gray-200 dark:border-gray-700 p-2 md:p-3 bg-white dark:bg-gray-800 sticky bottom-0">
        <ActiveScopeBar
          scope={appliedScope}
          onClearSlot={onClearSlot}
          onClearAll={onClearAll}
        />
        <ChatComposer
          ref={textareaRef}
          value={draft}
          onChange={setDraft}
          onSend={handleSend}
          isSending={isSending}
        />
        {/* Error 領域 */}
        {error && !dismissedError && (
          <div className="mt-2 flex items-start justify-between gap-2 text-xs rounded border border-red-300 bg-red-50 dark:bg-red-900/30 px-3 py-2 text-red-700 dark:text-red-200">
            <span className="break-words">{t(error)}</span>
            <button
              type="button"
              onClick={() => setDismissedError(true)}
              aria-label={t('auto.AdviceChat.cancel')}
              className="text-red-700 dark:text-red-200 hover:opacity-75 text-sm leading-none"
            >
              ×
            </button>
          </div>
        )}
      </div>

      <ResetConfirmModal
        open={resetOpen}
        onCancel={() => setResetOpen(false)}
        onConfirm={onConfirmReset}
      />
    </div>
  )
}
