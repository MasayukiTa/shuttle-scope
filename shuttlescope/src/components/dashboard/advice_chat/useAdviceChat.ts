/**
 * useAdviceChat — Growth Advisor (β) チャット用フック。
 *
 * 仕様 (このスライスは MVP / 最小機能版):
 *   - セッションは「初回 sendMessage 呼び出し時」に lazy create する。
 *     ユーザがチャットを開いても話しかけなければ DB にセッションは作らない。
 *   - 作成した session_id は localStorage (`growth_advisor_session_id`) に保存し、
 *     reload しても会話履歴を継続できる。GET 履歴が 404 を返した場合 (= 古い id /
 *     soft-deleted) は localStorage を消して "新規セッション扱い" にフォールバックする。
 *   - sendMessage: optimistic に user メッセージを即時追加 → POST 成功時に
 *     サーバから返った正規メッセージで置き換える。
 *   - error は i18n キー (auto.AdviceChat.error_*) で保持する。Component 側で t() する。
 *   - resetSession: DELETE → localStorage と state を全クリア。
 *
 * 後続スライスで Typewriter / fade / sticky 等の polish を追加する。本フックは
 * UI レイヤを問わない pure data hook として書く。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiDelete, apiGet, apiPost } from '@/api/client'

const STORAGE_KEY = 'growth_advisor_session_id'

export interface ChatMessage {
  id: number | string
  turn: number
  author: 'user' | 'ai' | 'system'
  content: string
  confidence?: number | null
  evidence_path?: string | null
  generator?: string | null
  is_fallback?: boolean
  validation_reason?: string | null
  date_from?: string | null
  date_to?: string | null
  /** scope snapshot at the turn this message was sent (user msgs only) */
  shot_type?: string | null
  zone?: string | null
  created_at?: string | null
  /** Optimistic で生成中のメッセージは true。サーバ応答で false になる。 */
  _pending?: boolean
}

export interface AppliedScope {
  period: { date_from: string | null; date_to: string | null; label?: string } | null
  shot_type: { code: string; label?: string } | null
  zone: { code: string; label?: string } | null
}

export interface SendOptions {
  period?: { dateFrom: string | null; dateTo: string | null } | null
  shotType?: string | null
  zone?: string | null
  clearSlots?: Array<'period' | 'shot_type' | 'zone'>
}

interface CreateSessionResp {
  session_id: number
  lang: string
  created_at: string
}

interface ListMessagesResp {
  messages: ChatMessage[]
  applied_scope?: AppliedScope | null
}

interface SendMessageResp {
  user_message: ChatMessage
  ai_message: ChatMessage
  applied_scope?: AppliedScope | null
}

interface HttpErrorLike {
  status?: number
  message?: string
}

function readStoredSid(): number | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (!v) return null
    const n = parseInt(v, 10)
    return Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

function writeStoredSid(sid: number | null): void {
  try {
    if (sid == null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(sid))
  } catch {
    // ignore
  }
}

function parseErrorBody(err: unknown): { code: string | null; status: number | null } {
  const e = err as HttpErrorLike
  const status = typeof e?.status === 'number' ? e.status : null
  let code: string | null = null
  try {
    // backend は HTTPException(detail={"error": "..."}) を JSON で返す
    const body = e?.message ? JSON.parse(e.message) : null
    const detail = body?.detail
    if (detail && typeof detail === 'object' && typeof detail.error === 'string') {
      code = detail.error
    } else if (typeof detail === 'string') {
      code = detail
    }
  } catch {
    /* not JSON */
  }
  return { code, status }
}

export function useAdviceChat() {
  const { i18n } = useTranslation()
  const lang: 'ja' | 'en' = i18n.language?.startsWith('en') ? 'en' : 'ja'

  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isInitializing, setIsInitializing] = useState<boolean>(false)
  const [isSending, setIsSending] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [appliedScope, setAppliedScope] = useState<AppliedScope | null>(null)

  // 同一マウント中の race condition 防止用
  const tempIdRef = useRef(0)

  // ── 初回マウント: localStorage の session_id があれば履歴を取得 ──
  useEffect(() => {
    const sid = readStoredSid()
    if (sid == null) return
    let cancelled = false
    setIsInitializing(true)
    apiGet<ListMessagesResp>(`/insights/chat/sessions/${sid}/messages`)
      .then((resp) => {
        if (cancelled) return
        setSessionId(sid)
        setMessages(resp.messages ?? [])
        setAppliedScope(resp.applied_scope ?? null)
      })
      .catch((err: unknown) => {
        const { status } = parseErrorBody(err)
        if (status === 404 || status === 403) {
          writeStoredSid(null)
        }
        // それ以外の error は無視 (ユーザが話しかけるまで session 未作成扱い)
      })
      .finally(() => {
        if (!cancelled) setIsInitializing(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const ensureSession = useCallback(async (): Promise<number> => {
    if (sessionId != null) return sessionId
    const resp = await apiPost<CreateSessionResp>('/insights/chat/sessions', { lang })
    setSessionId(resp.session_id)
    writeStoredSid(resp.session_id)
    return resp.session_id
  }, [sessionId, lang])

  const sendMessage = useCallback(
    async (
      content: string,
      opts?: SendOptions | null,
    ): Promise<void> => {
      const trimmed = content.trim()
      if (!trimmed || isSending) return
      setError(null)
      setIsSending(true)

      const periodDateFrom = opts?.period?.dateFrom ?? null
      const periodDateTo = opts?.period?.dateTo ?? null
      const shotType = opts?.shotType ?? null
      const zone = opts?.zone ?? null
      const clearSlots = opts?.clearSlots ?? []

      // ── optimistic user message ──
      tempIdRef.current += 1
      const tempId = `tmp-${tempIdRef.current}`
      const optimistic: ChatMessage = {
        id: tempId,
        turn: -1,
        author: 'user',
        content: trimmed,
        date_from: periodDateFrom,
        date_to: periodDateTo,
        shot_type: shotType,
        zone: zone,
        _pending: true,
      }
      setMessages((prev) => [...prev, optimistic])

      try {
        const sid = await ensureSession()
        const resp = await apiPost<SendMessageResp>(
          `/insights/chat/sessions/${sid}/messages`,
          {
            content: trimmed,
            date_from: periodDateFrom,
            date_to: periodDateTo,
            shot_type: shotType,
            zone: zone,
            clear_slots: clearSlots,
          },
        )
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== tempId)
          return [...without, resp.user_message, resp.ai_message]
        })
        if (resp.applied_scope !== undefined) {
          setAppliedScope(resp.applied_scope ?? null)
        }
      } catch (err) {
        // optimistic message を撤回
        setMessages((prev) => prev.filter((m) => m.id !== tempId))
        const { code, status } = parseErrorBody(err)
        if (code === 'rate_limited') {
          setError('auto.AdviceChat.error_rate_limited')
        } else if (code === 'budget_exceeded') {
          setError('auto.AdviceChat.error_budget_exceeded')
        } else if (status == null) {
          setError('auto.AdviceChat.error_network')
        } else {
          setError('auto.AdviceChat.error_generic')
        }
      } finally {
        setIsSending(false)
      }
    },
    [ensureSession, isSending],
  )

  const resetSession = useCallback(async (): Promise<void> => {
    setError(null)
    const sid = sessionId
    setSessionId(null)
    setMessages([])
    setAppliedScope(null)
    writeStoredSid(null)
    if (sid != null) {
      try {
        await apiDelete(`/insights/chat/sessions/${sid}`)
      } catch {
        // best-effort: ローカル状態は既に消したので無視
      }
    }
  }, [sessionId])

  return {
    sessionId,
    messages,
    isInitializing,
    isSending,
    error,
    sendMessage,
    resetSession,
    appliedScope,
  }
}
