// 汎用 LLM チャット (/#/llm)。admin / `llm` grant ユーザのみ (ルートで PageAccessRoute ガード)。
// 会話はユーザごとに分離 (backend で所有者強制)。メモリ=各会話のターン履歴 (SSE ストリーミング)。
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '../components/common/MIcon'
import {
  createConversation,
  deleteConversation,
  getLlmConfig,
  getMessages,
  listConversations,
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
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

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
  }, [messages, streamText])

  const onNewChat = useCallback(async () => {
    setActiveId(null)
    setMessages([])
    setInput('')
    setError(null)
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

    let acc = ''
    await streamMessage(convId, content, (e) => {
      if (e.type === 'delta' && e.content) {
        acc += e.content
        setStreamText(acc)
      } else if (e.type === 'error') {
        setError(e.message || t('llm.error.generate'))
      }
    })

    // ストリーム完了 → サーバの確定状態で再同期
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

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)] bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100">
      {/* 会話サイドバー */}
      <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-slate-200 dark:border-slate-700">
        <button
          onClick={onNewChat}
          className="m-3 inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-bold text-white hover:bg-blue-700"
        >
          <MIcon name="add" size={18} ariaHidden className="text-white" />
          {t('llm.new_chat')}
        </button>
        <div className="flex-1 overflow-y-auto px-2 pb-3">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center gap-1 rounded-md px-2 py-2 text-sm cursor-pointer ${
                c.id === activeId
                  ? 'bg-slate-100 dark:bg-slate-800'
                  : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
              }`}
              onClick={() => setActiveId(c.id)}
            >
              <MIcon name="forum" size={16} ariaHidden className="text-slate-400 shrink-0" />
              <span className="flex-1 truncate">{c.title}</span>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(c.id) }}
                className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500"
                aria-label={t('llm.delete')}
                title={t('llm.delete')}
              >
                <MIcon name="delete" size={16} ariaHidden />
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* チャット本体 */}
      <main className="flex flex-1 flex-col min-w-0">
        <header className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700 px-4 py-2.5">
          <MIcon name="smart_toy" size={20} ariaHidden className="text-blue-600" />
          <span className="font-bold">{t('llm.title')}</span>
          {config?.model && (
            <span className="ml-2 text-xs text-slate-400 truncate">{config.provider} · {config.model}</span>
          )}
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {messages.length === 0 && !streamText && (
            <div className="flex h-full flex-col items-center justify-center text-center text-slate-400">
              <MIcon name="smart_toy" size={40} ariaHidden className="mb-2" />
              <p className="text-sm">{t('llm.empty')}</p>
            </div>
          )}
          {messages.map((m) => (
            <Bubble key={m.id} role={m.role} content={m.content} />
          ))}
          {streamText && <Bubble role="assistant" content={streamText} pending />}
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
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder={t('llm.placeholder')}
              disabled={sending}
              className="w-full resize-none rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 pr-12 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
            />
            <button
              onClick={onSend}
              disabled={sending || !input.trim()}
              className="absolute right-2 bottom-2 inline-flex h-9 w-9 items-center justify-center rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
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

function Bubble({ role, content, pending }: { role: string; content: string; pending?: boolean }) {
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
  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[85%] rounded-2xl rounded-tl-sm bg-slate-100 dark:bg-slate-800 px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
          pending ? 'opacity-90' : ''
        }`}
      >
        {content}
        {pending && <span className="ml-1 inline-block animate-pulse">▌</span>}
      </div>
    </div>
  )
}
