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

// 「最下部付近」判定のしきい値 (px)。これより上にスクロールしていれば自動追従しない。
const SCROLL_BOTTOM_THRESHOLD = 80

// 「じっくり考える」(deep thinking) トグルの永続化キー。
const THINKING_STORAGE_KEY = 'ss.llm.thinking'

function readThinkingPref(): boolean {
  try {
    return localStorage.getItem(THINKING_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

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
  const [reasoningText, setReasoningText] = useState('') // 推論モデルの思考過程 (ライブのみ、永続化されない)
  const [thinking, setThinking] = useState(readThinkingPref) // 「じっくり考える」トグル (localStorage 永続)
  const [error, setError] = useState<string | null>(null)
  const [retryPrompt, setRetryPrompt] = useState<string | null>(null) // 送信失敗したプロンプト (再試行用)
  const [renamingId, setRenamingId] = useState<number | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false) // モバイル会話ドロワー (<md)
  const [messagesLoading, setMessagesLoading] = useState(false) // 会話切替時のメッセージ取得中
  const [showScrollDown, setShowScrollDown] = useState(false) // 上にスクロール中の「最新へ」ボタン
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null) // 削除確認中の会話
  const scrollRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const forceScrollRef = useRef(true) // 会話切替直後は閾値に関係なく最下部へ寄せる
  const abortRef = useRef<AbortController | null>(null) // 進行中ストリームの中断用
  const drawerRef = useRef<HTMLDivElement>(null) // フォーカストラップ対象 (ドロワー内)
  const menuBtnRef = useRef<HTMLButtonElement>(null) // ドロワーを開いたハンバーガー (閉じたらここへ復帰)

  const notConfigured = config != null && !config.configured

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

  // 「じっくり考える」トグル状態を localStorage に永続化。
  useEffect(() => {
    try {
      localStorage.setItem(THINKING_STORAGE_KEY, thinking ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [thinking])

  const reasoningAvailable = config?.reasoning_available === true

  useEffect(() => {
    forceScrollRef.current = true // 会話を切り替えたら次回描画で最下部へ
    if (activeId == null) {
      setMessages([])
      return
    }
    let cancelled = false
    setMessagesLoading(true)
    getMessages(activeId)
      .then((r) => { if (!cancelled) setMessages(r.messages || []) })
      .catch(() => { if (!cancelled) setMessages([]) })
      .finally(() => { if (!cancelled) setMessagesLoading(false) })
    return () => { cancelled = true }
  }, [activeId])

  // 自動スクロール: ユーザが最下部付近にいるときだけ追従。上に戻していれば位置を保持。
  // ただし会話切替直後 (forceScrollRef) は無条件で最下部へ。
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    if (forceScrollRef.current || distance <= SCROLL_BOTTOM_THRESHOLD) {
      el.scrollTop = el.scrollHeight
      forceScrollRef.current = false
    }
  }, [messages, streamText, streaming, reasoningText])

  // スクロール位置を監視して「最新へ」ボタンの表示を切り替える。
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight
      setShowScrollDown(distance > SCROLL_BOTTOM_THRESHOLD)
    }
    onScroll()
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [activeId])

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  // 入力 textarea の自動高さ調整 (1 行〜最大 ~6 行 = 160px、超過分はスクロール)。
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [input])

  // ドロワーを開いている間は背面スクロールをロック + Esc で閉じる + Tab フォーカストラップ。
  // 開いたら最初のフォーカス可能要素へ移動、閉じたら開いたボタン (ハンバーガー) へ復帰。
  useEffect(() => {
    if (!drawerOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const opener = menuBtnRef.current

    const focusables = () => {
      const root = drawerRef.current
      if (!root) return [] as HTMLElement[]
      return Array.from(
        root.querySelectorAll<HTMLElement>(
          'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute('disabled') && el.offsetParent !== null)
    }

    // 開いた直後に最初のコントロールへフォーカス。
    const focusTimer = window.setTimeout(() => {
      const els = focusables()
      els[0]?.focus()
    }, 0)

    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDrawerOpen(false)
        return
      }
      if (e.key !== 'Tab') return
      const els = focusables()
      if (els.length === 0) return
      const first = els[0]
      const last = els[els.length - 1]
      const active = document.activeElement as HTMLElement | null
      if (e.shiftKey) {
        if (active === first || !drawerRef.current?.contains(active)) {
          e.preventDefault()
          last.focus()
        }
      } else if (active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.clearTimeout(focusTimer)
      document.body.style.overflow = prev
      window.removeEventListener('keydown', onKey)
      // 閉じたらハンバーガーへフォーカスを戻す (画面に残っている場合)。
      opener?.focus()
    }
  }, [drawerOpen])

  // アンマウント時に進行中ストリームを中断 (リーク防止)。
  useEffect(() => () => abortRef.current?.abort(), [])

  const onNewChat = useCallback(async () => {
    setActiveId(null)
    setMessages([])
    setInput('')
    setError(null)
    setRetryPrompt(null)
    setDrawerOpen(false)
  }, [])

  const onSelectConversation = useCallback((id: number) => {
    setActiveId(id)
    setDrawerOpen(false)
  }, [])

  // メッセージ送信。retry から呼ぶ場合は overrideContent を渡す (入力欄の値ではなく失敗プロンプトを再送)。
  const onSend = useCallback(async (overrideContent?: string) => {
    const content = (overrideContent ?? input).trim()
    if (!content || sending || notConfigured) return
    setError(null)
    setRetryPrompt(null)
    setSending(true)
    // 入力欄からの送信時のみクリア (retry は入力欄に触れない)。
    if (overrideContent == null) setInput('')

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
      // データ消失防止: 失敗したプロンプトを入力欄へ戻す + 再試行を可能にする。
      setInput(content)
      setRetryPrompt(content)
      setSending(false)
      return
    }

    // ユーザ発言を即時表示 (失敗しても残す)
    const optimistic: LlmMessage = { id: -Date.now(), seq: messages.length + 1, role: 'user', content }
    setMessages((prev) => [...prev, optimistic])
    setStreamText('')
    setReasoningText('') // 新規送信ごとに前回の思考過程をクリア (ライブのみ表示)
    setStreaming(true) // start/delta 前から「生成中」を表示 (応答までの空白時間も可視化)

    // この送信時点のトグル値を確定 (送信中にトグルが変わっても影響させない)。
    const useThinking = thinking

    // 中断用 AbortController を都度生成。
    const controller = new AbortController()
    abortRef.current = controller

    let acc = ''
    let reasoningAcc = ''
    let aborted = false
    let errored = false
    try {
      await streamMessage(convId, content, (e) => {
        if (e.type === 'start') {
          setStreaming(true)
        } else if (e.type === 'delta' && e.content) {
          acc += e.content
          setStreaming(true)
          setStreamText(acc)
        } else if (e.type === 'reasoning' && e.content) {
          // 推論モデルの思考過程をライブ蓄積 (確定メッセージには残さない)。
          reasoningAcc += e.content
          setStreaming(true)
          setReasoningText(reasoningAcc)
        } else if (e.type === 'done') {
          setStreaming(false)
        } else if (e.type === 'error') {
          // ユーザによる中断 (AbortSignal) はエラー扱いしない。
          if (controller.signal.aborted) {
            aborted = true
            return
          }
          errored = true
          setStreaming(false)
          // ミッドストリームエラー: 既出のストリームテキストは消さず確定バブル + エラー注記にする。
          setError(e.message || t('llm.error.generate'))
        }
      }, controller.signal, useThinking)
    } catch {
      // reader.read() が中断/失敗で reject した場合 (llm.ts の loop は try/catch を持たない)。
      // 中断ならエラー扱いせず、それ以外は通常エラーとして部分テキストを保持する。
      if (controller.signal.aborted) {
        aborted = true
      } else {
        errored = true
        setError(t('llm.error.generate'))
      }
    }

    abortRef.current = null
    setStreaming(false)
    setSending(false)
    // 思考過程はライブのみ (永続化されない)。中断/エラー/正常完了いずれの終了時もクリアし、確定メッセージには残さない。
    setReasoningText('')

    // ユーザ中断: 部分テキストを assistant バブルとして残し、エラーは出さない。再同期もしない。
    if (aborted || controller.signal.aborted) {
      if (acc) {
        setMessages((prev) => [...prev, { id: -Date.now() - 1, seq: prev.length + 1, role: 'assistant', content: acc }])
      }
      setStreamText('')
      refreshConversations()
      return
    }

    // ミッドストリームエラー: 既に届いた部分テキストを確定バブルとして残す (再同期で上書きしない)。
    if (errored) {
      if (acc) {
        setMessages((prev) => [...prev, { id: -Date.now() - 1, seq: prev.length + 1, role: 'assistant', content: acc }])
      }
      setStreamText('')
      return
    }

    // 正常完了 → サーバの確定状態で再同期
    setStreamText('')
    try {
      const r = await getMessages(convId)
      setMessages(r.messages || [])
    } catch {
      if (acc) {
        setMessages((prev) => [...prev, { id: -Date.now() - 1, seq: prev.length + 1, role: 'assistant', content: acc }])
      }
    }
    refreshConversations()
  }, [input, sending, notConfigured, activeId, messages.length, refreshConversations, thinking, t])

  // 生成停止 (STOP ボタン)。signal.abort() でストリームを打ち切る。後処理は onSend 側で行う。
  const onStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

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

  // 削除は確認を挟む: 1 度目で確認状態、2 度目 (確認ボタン) で実行。
  const requestDelete = useCallback((id: number) => {
    setConfirmDeleteId(id)
  }, [])

  const cancelDelete = useCallback(() => {
    setConfirmDeleteId(null)
  }, [])

  const confirmDelete = useCallback((id: number) => {
    setConfirmDeleteId(null)
    onDelete(id)
  }, [onDelete])

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
    // IME 変換確定の Enter では送信しない (日本語入力で誤送信を防ぐ)。
    if (e.key === 'Enter' && !e.shiftKey && !(e.nativeEvent as { isComposing?: boolean }).isComposing) {
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
    confirmDeleteId,
    onNewChat,
    onSelectConversation,
    requestDelete,
    cancelDelete,
    confirmDelete,
    startRename,
    cancelRename,
    commitRename,
    setRenameDraft,
  }

  const composerDisabled = sending || notConfigured

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
          <div ref={drawerRef} className="absolute inset-y-0 left-0 flex w-72 max-w-[80%] flex-col bg-white dark:bg-slate-900 shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-700 px-3 py-2.5">
              <span className="font-bold text-sm">{t('llm.conversations')}</span>
              <button
                onClick={() => setDrawerOpen(false)}
                className="inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
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
            ref={menuBtnRef}
            onClick={() => setDrawerOpen(true)}
            className="md:hidden inline-flex h-11 w-11 -ml-2 items-center justify-center rounded-md text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label={t('llm.open_conversations')}
            title={t('llm.open_conversations')}
          >
            <MIcon name="menu" size={22} ariaHidden />
          </button>
          <MIcon name="smart_toy" size={20} ariaHidden className="text-blue-600" />
          <span className="font-bold">{t('llm.title')}</span>
        </header>

        <div className="relative flex-1 min-h-0">
          <div ref={scrollRef} className="absolute inset-0 overflow-y-auto px-4 py-4 space-y-3">
            {messagesLoading && messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center text-slate-500 dark:text-slate-400">
                <span className="flex gap-1 mb-2" aria-hidden>
                  <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
                <p className="text-sm">{t('llm.loading')}</p>
              </div>
            ) : (
              messages.length === 0 && !streamText && !streaming && (
                <div className="flex h-full flex-col items-center justify-center text-center text-slate-500 dark:text-slate-400">
                  <MIcon name="smart_toy" size={40} ariaHidden className="mb-2" />
                  <p className="text-sm">{t('llm.empty')}</p>
                </div>
              )
            )}
            {messages.map((m) => (
              <Bubble key={m.id} role={m.role} content={m.content} />
            ))}
            {/* ストリーミング中の応答領域: スクリーンリーダーへ読み上げ (aria-live) + 生成中は aria-busy。 */}
            <div aria-live="polite" aria-busy={streaming || undefined}>
              {/* 思考過程 (推論モデルの chain-of-thought): 回答バブルの上に折りたたみ表示。ライブのみ (確定時にクリア)。 */}
              {reasoningText && (
                <ReasoningBlock content={reasoningText} label={t('llm.thinking_process')} />
              )}
              {streamText && <Bubble role="assistant" content={streamText} pending />}
              {streaming && !streamText && <TypingIndicator label={t('llm.generating')} />}
            </div>
          </div>

          {/* 上にスクロール中だけ表示する「最新へ」フローティングボタン */}
          {showScrollDown && (
            <button
              type="button"
              onClick={scrollToBottom}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 inline-flex h-10 items-center gap-1 rounded-full bg-slate-700 dark:bg-slate-600 px-3 text-xs font-medium text-white shadow-lg hover:bg-slate-800 dark:hover:bg-slate-500"
              aria-label={t('llm.scroll_to_latest')}
              title={t('llm.scroll_to_latest')}
            >
              <MIcon name="arrow_downward" size={16} ariaHidden className="text-white" />
              {t('llm.scroll_to_latest')}
            </button>
          )}
        </div>

        {error && (
          <div role="alert" className="mx-4 mb-2 flex items-start gap-2 rounded-md bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm text-red-700 dark:text-red-300">
            <span className="flex-1">{error}</span>
            {retryPrompt && (
              <button
                type="button"
                onClick={() => onSend(retryPrompt)}
                disabled={sending}
                className="inline-flex items-center gap-1 rounded px-2 py-0.5 font-medium text-red-700 dark:text-red-200 underline hover:no-underline disabled:opacity-50"
              >
                <MIcon name="refresh" size={14} ariaHidden />
                {t('llm.retry')}
              </button>
            )}
          </div>
        )}
        {notConfigured && (
          <div className="mx-4 mb-2 rounded-md bg-amber-50 dark:bg-amber-900/30 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            {t('llm.not_configured')}
          </div>
        )}

        <div className="border-t border-slate-200 dark:border-slate-700 p-3">
          {/* 「じっくり考える」(deep thinking) トグル: reasoning 対応時のみ表示。状態を localStorage に永続化。 */}
          {reasoningAvailable && (
            <div className="mb-2 flex">
              <button
                type="button"
                onClick={() => setThinking((v) => !v)}
                aria-pressed={thinking}
                title={t('llm.think_deeply')}
                className={`inline-flex min-h-[36px] items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  thinking
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
                }`}
              >
                <MIcon name="lightbulb" size={16} fill={thinking ? 1 : 0} ariaHidden className={thinking ? 'text-white' : undefined} />
                {t('llm.think_deeply')}
              </button>
            </div>
          )}
          <div className="relative">
            <textarea
              ref={taRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder={notConfigured ? t('llm.not_configured_hint') : t('llm.placeholder')}
              className="block w-full resize-none rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 pr-14 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500 max-h-40 overflow-y-auto"
            />
            {streaming ? (
              <button
                onClick={onStop}
                className="absolute right-1.5 bottom-1.5 inline-flex h-11 w-11 items-center justify-center rounded-md bg-rose-600 text-white hover:bg-rose-700"
                aria-label={t('llm.stop')}
                title={t('llm.stop')}
              >
                <MIcon name="stop" size={20} ariaHidden className="text-white" />
              </button>
            ) : (
              <button
                onClick={() => onSend()}
                disabled={composerDisabled || !input.trim()}
                className="absolute right-1.5 bottom-1.5 inline-flex h-11 w-11 items-center justify-center rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                aria-label={t('llm.send')}
                title={t('llm.send')}
              >
                <MIcon name="send" size={18} ariaHidden className="text-white" />
              </button>
            )}
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
  confirmDeleteId: number | null
  onNewChat: () => void
  onSelectConversation: (id: number) => void
  requestDelete: (id: number) => void
  cancelDelete: () => void
  confirmDelete: (id: number) => void
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
  confirmDeleteId,
  onNewChat,
  onSelectConversation,
  requestDelete,
  cancelDelete,
  confirmDelete,
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
            {confirmDeleteId === c.id ? (
              // 削除確認: 実行 / キャンセルの 2 ボタンをインライン表示。
              <>
                <button
                  onClick={(e) => { e.stopPropagation(); confirmDelete(c.id) }}
                  className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-red-500 hover:text-red-600"
                  aria-label={t('llm.confirm_delete')}
                  title={t('llm.confirm_delete')}
                >
                  <MIcon name="check" size={16} ariaHidden />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); cancelDelete() }}
                  className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                  aria-label={t('llm.cancel')}
                  title={t('llm.cancel')}
                >
                  <MIcon name="close" size={16} ariaHidden />
                </button>
              </>
            ) : (
              <>
                {renamingId === c.id ? (
                  <button
                    onClick={(e) => { e.stopPropagation(); commitRename(c.id) }}
                    className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                    aria-label={t('llm.save')}
                    title={t('llm.save')}
                  >
                    <MIcon name="check" size={16} ariaHidden />
                  </button>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); startRename(c) }}
                    className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 opacity-100 md:opacity-0 md:group-hover:opacity-100"
                    aria-label={t('llm.rename')}
                    title={t('llm.rename')}
                  >
                    <MIcon name="edit" size={16} ariaHidden />
                  </button>
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); requestDelete(c.id) }}
                  className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-slate-400 hover:text-red-500 opacity-100 md:opacity-0 md:group-hover:opacity-100"
                  aria-label={t('llm.delete')}
                  title={t('llm.delete')}
                >
                  <MIcon name="delete" size={16} ariaHidden />
                </button>
              </>
            )}
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
  // assistant: Markdown 描画 (コードブロック/箇条書き等)。ChatMarkdown は未閉鎖フェンスも許容するため
  // ストリーミング中 (pending) も Markdown 描画し、確定時の再レイアウトちらつきを無くす。
  return (
    <div className="group flex flex-col items-start">
      <div className={`max-w-[85%] rounded-2xl rounded-tl-sm bg-slate-100 dark:bg-slate-800 px-3.5 py-2 text-sm leading-relaxed break-words ${pending ? 'opacity-90' : ''}`}>
        <ChatMarkdown content={content} />
        {pending && <span className="ml-1 inline-block animate-pulse align-baseline">▌</span>}
      </div>
      {!pending && content && (
        <button
          onClick={onCopy}
          className="mt-1 inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-500 transition-opacity hover:text-slate-600 dark:text-slate-400 dark:hover:text-slate-300 opacity-100 md:opacity-0 md:group-hover:opacity-100"
          aria-label={t('llm.copy')}
          title={t('llm.copy')}
        >
          <MIcon name={copied ? 'check' : 'content_copy'} size={14} ariaHidden />
          {copied ? t('llm.copied') : t('llm.copy')}
        </button>
      )}
      {/* コピー成功をスクリーンリーダーへ通知 (視覚表示はボタン側ラベルで実施)。 */}
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? t('llm.copied') : ''}
      </span>
    </div>
  )
}

// 応答生成中インジケータ: assistant 吹き出し風に波打つ 3 点 + 「生成中」ラベル。
// SSE の start〜最初の delta が来るまでの空白時間を可視化する (streaming && !streamText のとき表示)。
function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-slate-100 dark:bg-slate-800 px-3.5 py-2.5">
        <span className="flex gap-1" aria-hidden>
          <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="h-2 w-2 rounded-full bg-slate-400 dark:bg-slate-500 animate-bounce" style={{ animationDelay: '300ms' }} />
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-500">{label}</span>
      </div>
    </div>
  )
}

// 思考プロセス (推論モデルの chain-of-thought) を回答バブルの上に折りたたみ表示する。
// ストリーミング中はデフォルト展開 (open)。muted で小さめのテキスト。ライブのみで永続化されない。
function ReasoningBlock({ content, label }: { content: string; label: string }) {
  return (
    <details
      open
      className="mb-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-3 py-2 text-slate-500 dark:text-slate-400"
    >
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium select-none">
        <MIcon name="lightbulb" size={14} ariaHidden />
        {label}
      </summary>
      <div className="mt-1.5 whitespace-pre-wrap break-words text-xs leading-relaxed opacity-90">
        {content}
      </div>
    </details>
  )
}
