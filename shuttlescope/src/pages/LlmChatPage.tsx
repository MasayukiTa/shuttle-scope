// 汎用 LLM チャット (/#/llm)。admin / `llm` grant ユーザのみ (ルートで PageAccessRoute ガード)。
// 会話はユーザごとに分離 (backend で所有者強制)。メモリ=各会話のターン履歴 (SSE ストリーミング)。
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '../components/common/MIcon'
import { ChatMarkdown } from '../components/common/ChatMarkdown'
import {
  createConversation,
  deleteConversation,
  getLlmConfig,
  getMessages,
  listConversations,
  renameConversation,
  streamMessage,
  type LlmConfig,
  type LlmConversation,
  type LlmMessage,
} from '../api/llm'

export default function LlmChatPage() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<LlmConfig | null>(null)
  const [conversations, setConversations] = useState<LlmConversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<LlmMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [streaming, setStreaming] = useState(false) // SSE start〜done/error の生成中フラグ
  const [error, setError] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false) // モバイル会話ドロワー (<md)
  const scrollRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const refreshConversations = useCallback(async () => {
    try {
      const r = await listConversations()
      setConversations(r.conversations || [])
      return r.conversations || []
    } catch {
      return []
    }
  }, [])

  useEffect(() => {
    getLlmConfig().then(setConfig).catch(() => setConfig(null))
    refreshConversations()
  }, [refreshConversations])

  useEffect(() => {
    if (activeId == null) {
      setMessages([])
      return
    }
    getMessages(activeId).then((r) => setMessages(r.messages || [])).catch(() => setMessages([]))
  }, [activeId])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, streamText, streaming])

  // 入力 textarea の自動高さ調整 (1 行〜最大 ~6 行 = 160px、超過分はスクロール)。
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [input])

  // ドロワーを開いている間は背面スクロールをロック + Esc で閉じる。
  useEffect(() => {
    if (!drawerOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
    }
  }, [drawerOpen])

  const onNewChat = useCallback(async () => {
    setActiveId(null)
    setMessages([])
    setInput('')
    setError(null)
    setDrawerOpen(false)
  }, [])

  const onSelectConversation = useCallback((id: number) => {
    setActiveId(id)
    setDrawerOpen(false)
  }, [])

  const onSend = useCallback(async () => {
    const content = input.trim()
    if (!content || sending) return
    setError(null)
    setSending(true)
    setInput('')

    // 会話が無ければ作成
    let convId = activeId
    try {
      if (convId == null) {
        const c = await createConversation({})
        convId = c.id
        setActiveId(c.id)
        setConversations((prev) => [c, ...prev])
      }
    } catch {
      setError(t('llm.error.create'))
      setSending(false)
      return
    }

    // ユーザ発言を即時表示
    const optimistic: LlmMessage = { id: -Date.now(), seq: messages.length + 1, role: 'user', content }
    setMessages((prev) => [...prev, optimistic])
    setStreamText('')
    setStreaming(true) // start/delta 前から「生成中」を表示 (応答までの空白時間も可視化)

    let acc = ''
    await streamMessage(convId, content, (e) => {
      if (e.type === 'start') {
        setStreaming(true)
      } else if (e.type === 'delta' && e.content) {
        acc += e.content
        setStreaming(true)
        setStreamText(acc)
      } else if (e.type === 'done') {
        setStreaming(false)
      } else if (e.type === 'error') {
        setStreaming(false)
        setError(e.message || t('llm.error.generate'))
      }
    })

    // ストリーム完了 → サーバの確定状態で再同期
    setStreaming(false)
    setStreamText('')
    try {
      const r = await getMessages(convId)
      setMessages(r.messages || [])
    } catch {
      if (acc) {
        setMessages((prev) => [...prev, { id: -Date.now() - 1, seq: prev.length + 1, role: 'assistant', content: acc }])
      }
    }
    setSending(false)
    refreshConversations()
  }, [input, sending, activeId, messages.length, refreshConversations, t])

  const onDelete = useCallback(async (id: number) => {
    try {
      await deleteConversation(id)
    } catch {
      /* ignore */
    }
    setConversations((prev) => prev.filter((c) => c.id !== id))
    if (activeId === id) {
      setActiveId(null)
      setMessages([])
    }
  }, [activeId])

  const startRename = useCallback((c: LlmConversation) => {
    setRenamingId(c.id)
    setRenameDraft(c.title)
  }, [])

  const cancelRename = useCallback(() => {
    setRenamingId(null)
    setRenameDraft('')
  }, [])

  const commitRename = useCallback(async (id: number) => {
    const title = renameDraft.trim()
    if (!title) { cancelRename(); return }
    // 即時反映 (失敗時はサーバ状態で巻き戻し)
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)))
    setRenamingId(null)
    setRenameDraft('')
    try {
      await renameConversation(id, title)
    } catch {
      setError(t('llm.error.rename'))
    }
    refreshConversations()
  }, [renameDraft, cancelRename, refreshConversations, t])

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  // デスクトップ aside とモバイルドロワーで同じ状態/ハンドラを共有 (state はフォークしない)。
  const listProps = {
    conversations,
    activeId,
    renamingId,
    renameDraft,
    onNewChat,
    onSelectConversation,
    onDelete,
    startRename,
    cancelRename,
    commitRename,
    setRenameDraft,
  }

  return (
    <div className="flex h-full bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100">
      {/* 会話サイドバー (デスクトップ) */}
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-slate-200 dark:border-slate-700">
        <ConversationList {...listProps} />
      </aside>

      {/* 会話ドロワー (モバイル <md): 左スライドイン + 暗転バックドロップ */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label={t('llm.conversations')}>
          <button
            type="button"
            aria-label={t('llm.close')}
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 bg-black/40"
          />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[80%] flex-col bg-white dark:bg-slate-900 shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-700 px-3 py-2.5">
              <span className="font-bold text-sm">{t('llm.conversations')}</span>
              <button
                onClick={() => setDrawerOpen(false)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label={t('llm.close')}
                title={t('llm.close')}
              >
                <MIcon name="close" size={20} ariaHidden />
              </button>
            </div>
            <ConversationList {...listProps} />
          </div>
        </div>
      )}

      {/* チャット本体 */}
      <main className="flex flex-1 flex-col min-w-0">
        <header className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 px-4 py-2.5">
          <button
            onClick={() => setDrawerOpen(true)}
            className="md:hidden inline-flex h-10 w-10 -ml-2 items-center justify-center rounded-md text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label={t('llm.open_conversations')}
            title={t('llm.open_conversations')}
          >
            <MIcon name="menu" size={22} ariaHidden />
          </button>
          <MIcon name="smart_toy" size={20} ariaHidden className="text-blue-600" />
          <span className="font-bold">{t('llm.title')}</span>
          {config?.model && (
            <span className="ml-2 text-xs text-slate-400 truncate">{config.provider} · {config.model}</span>
          )}
        </header>

        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-3">
          {messages.length === 0 && !streamText && !streaming && (
            <div className="flex h-full flex-col items-center justify-center text-center text-slate-400">
              <MIcon name="smart_toy" size={40} ariaHidden className="mb-2" />
              <p className="text-sm">{t('llm.empty')}</p>
            </div>
          )}
          {messages.map((m) => (
            <Bubble key={m.id} role={m.role} content={m.content} />
          ))}
          {streamText && <Bubble role="assistant" content={streamText} pending />}
          {streaming && !streamText && <TypingIndicator label={t('llm.generating')} />}
        </div>

        {error && (
          <div className="mx-4 mb-2 rounded-md bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm text-red-700 dark:text-red-300">
            {error}
          </div>
        )}
        {config && !config.configured && (
          <div className="mx-4 mb-2 rounded-md bg-amber-50 dark:bg-amber-900/30 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            {t('llm.not_configured')}
          </div>
        )}

        <div className="border-t border-slate-200 dark:border-slate-700 p-3">
          <div className="relative">
            <textarea
              ref={taRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder={t('llm.placeholder')}
              disabled={sending}
              className="block w-full resize-none rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 pr-14 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 max-h-40 overflow-y-auto"
            />
            <button
              onClick={onSend}
              disabled={sending || !input.trim()}
              className="absolute right-1.5 bottom-1.5 inline-flex h-10 w-10 items-center justify-center rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              aria-label={t('llm.send')}
              title={t('llm.send')}
            >
              <MIcon name="send" size={18} ariaHidden className="text-white" />
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}

// 会話リスト本体 (new-chat ボタン + 会話行)。デスクトップ aside とモバイルドロワーで共有。
interface ConversationListProps {
  conversations: LlmConversation[]
  activeId: number | null
  renamingId: number | null
  renameDraft: string
  onNewChat: () => void
  onSelectConversation: (id: number) => void
  onDelete: (id: number) => void
  startRename: (c: LlmConversation) => void
  cancelRename: () => void
  commitRename: (id: number) => void
  setRenameDraft: (v: string) => void
}

function ConversationList({
  conversations,
  activeId,
  renamingId,
  renameDraft,
  onNewChat,
  onSelectConversation,
  onDelete,
  startRename,
  cancelRename,
  commitRename,
  setRenameDraft,
}: ConversationListProps) {
  const { t } = useTranslation()
  return (
    <>
      <button
        onClick={onNewChat}
        className="m-3 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-bold text-white hover:bg-blue-700"
      >
        <MIcon name="add" size={18} ariaHidden className="text-white" />
        {t('llm.new_chat')}
      </button>
      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`group flex items-center gap-1 rounded-md px-2 py-2 text-sm ${
              renamingId === c.id ? '' : 'cursor-pointer'
            } ${
              c.id === activeId
                ? 'bg-slate-100 dark:bg-slate-800'
                : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
            }`}
            onClick={() => { if (renamingId !== c.id) onSelectConversation(c.id) }}
          >
            <MIcon name="forum" size={16} ariaHidden className="text-slate-400 shrink-0" />
            {renamingId === c.id ? (
              <input
                autoFocus
                value={renameDraft}
                onChange={(e) => setRenameDraft(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); commitRename(c.id) }
                  else if (e.key === 'Escape') { e.preventDefault(); cancelRename() }
                }}
                onBlur={() => commitRename(c.id)}
                maxLength={200}
                placeholder={t('llm.rename_placeholder')}
                aria-label={t('llm.rename')}
                className="flex-1 min-w-0 rounded border border-blue-500 bg-white dark:bg-slate-900 px-1.5 py-0.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            ) : (
              <span className="flex-1 truncate">{c.title}</span>
            )}
            {renamingId === c.id ? (
              <button
                onClick={(e) => { e.stopPropagation(); commitRename(c.id) }}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                aria-label={t('llm.save')}
                title={t('llm.save')}
              >
                <MIcon name="check" size={16} ariaHidden />
              </button>
            ) : (
              <button
                onClick={(e) => { e.stopPropagation(); startRename(c) }}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 opacity-100 md:opacity-0 md:group-hover:opacity-100"
                aria-label={t('llm.rename')}
                title={t('llm.rename')}
              >
                <MIcon name="edit" size={16} ariaHidden />
              </button>
            )}
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(c.id) }}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center text-slate-400 hover:text-red-500 opacity-100 md:opacity-0 md:group-hover:opacity-100"
              aria-label={t('llm.delete')}
              title={t('llm.delete')}
            >
              <MIcon name="delete" size={16} ariaHidden />
            </button>
          </div>
        ))}
      </div>
    </>
  )
}

function Bubble({ role, content, pending }: { role: string; content: string; pending?: boolean }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const isUser = role === 'user'
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[78%] rounded-2xl rounded-tr-sm bg-blue-600 px-3.5 py-2 text-sm leading-relaxed text-white whitespace-pre-wrap break-words">
          {content}
        </div>
      </div>
    )
  }
  const onCopy = () => {
    try {
      navigator.clipboard?.writeText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard 非対応環境 (http 等) は無視 */ }
  }
  // assistant: 確定メッセージは Markdown 描画 (コードブロック/箇条書き等)。
  // ストリーミング中 (pending) は再レイアウトのちらつきを避け素のテキスト + カーソル。
  return (
    <div className="group flex flex-col items-start">
      <div className={`max-w-[85%] rounded-2xl rounded-tl-sm bg-slate-100 dark:bg-slate-800 px-3.5 py-2 text-sm leading-relaxed break-words ${pending ? 'opacity-90' : ''}`}>
        {pending ? (
          <span className="whitespace-pre-wrap">{content}<span className="ml-1 inline-block animate-pulse">▌</span></span>
        ) : (
          <ChatMarkdown content={content} />
        )}
      </div>
      {!pending && content && (
        <button
          onClick={onCopy}
          className="mt-1 inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-400 transition-opacity hover:text-slate-600 dark:hover:text-slate-300 opacity-100 md:opacity-0 md:group-hover:opacity-100"
          aria-label={t('llm.copy')}
          title={t('llm.copy')}
        >
          <MIcon name={copied ? 'check' : 'content_copy'} size={14} ariaHidden />
          {copied ? t('llm.copied') : t('llm.copy')}
        </button>
      )}
    </div>
  )
}

// 応答生成中インジケータ: assistant 吹き出し風に波打つ 3 点 + 「生成中」ラベル。
// SSE の start〜最初の delta が来るまでの空白時間を可視化する (streaming && !streamText のとき表示)。
function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="flex justify-start" role="status" aria-live="polite">
      <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-slate-100 dark:bg-slate-800 px-3.5 py-2.5">
        <span className="flex gap-1" aria-hidden>
          <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '300ms' }} />
        </span>
        <span className="text-xs text-slate-400 dark:text-slate-500">{label}</span>
      </div>
    </div>
  )
}
