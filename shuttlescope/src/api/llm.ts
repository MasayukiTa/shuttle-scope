// 汎用 LLM チャット (/#/llm) の API クライアント。
// 会話 CRUD は通常の apiGet/apiPost、メッセージ送信のみ SSE ストリーミングを生 fetch で扱う。
import { API_BASE_URL, apiGet, apiPost, apiPatch, apiDelete, fetchAuthed } from './client'

export interface LlmConversation {
  id: number
  title: string
  created_at?: string | null
  last_used_at?: string | null
}

export interface LlmMessage {
  id: number
  seq: number
  role: string
  content: string
  // 添付画像 (data URL "data:image/...;base64,..." の配列)。user メッセージのみ。
  // backend が返さない場合もあるため optional。
  images?: string[] | null
  created_at?: string | null
}

export interface LlmConfig {
  configured: boolean
  streaming: boolean
  reasoning_available: boolean
}

// モデルピッカーの 1 選択肢。label は backend (registry の curated allowlist) が返す
// 表示名で、UI 側ではハードコードしない (i18n もしない)。
export interface LlmModel {
  id: string
  label: string
}

// SSE イベント種別。reasoning は推論モデルの思考過程 (chain-of-thought) をライブ配信する (永続化されない)。
export type StreamEvent = {
  type: 'start' | 'delta' | 'reasoning' | 'done' | 'error'
  content?: string
  message?: string
  thinking?: boolean
}

// Stable codes the backend sends in the SSE error event (see _classify_stream_error in
// backend/routers/llm_chat.py) and the i18n key that explains each one. Raw upstream text
// never reaches the client, so an unknown message falls back to the generic key.
const LLM_STREAM_ERROR_KEYS = {
  budget_exceeded: 'llm.error.budget_exceeded',
  provider_timeout: 'llm.error.provider_timeout',
  provider_unavailable: 'llm.error.provider_unavailable',
  provider_rate_limited: 'llm.error.provider_rate_limited',
  provider_auth: 'llm.error.provider_auth',
  provider_rejected: 'llm.error.provider_rejected',
  generation_failed: 'llm.error.generate',
} as const

export type LlmStreamErrorKey = (typeof LLM_STREAM_ERROR_KEYS)[keyof typeof LLM_STREAM_ERROR_KEYS]

export function llmStreamErrorKey(message: string | undefined): LlmStreamErrorKey | null {
  if (!message || !Object.prototype.hasOwnProperty.call(LLM_STREAM_ERROR_KEYS, message)) return null
  return LLM_STREAM_ERROR_KEYS[message as keyof typeof LLM_STREAM_ERROR_KEYS]
}

// backend が構造化 detail ({"error": "budget_exceeded"} 等) を返したときの安定コードを取り出す。
// detail が文字列ならそのまま、object なら error / code、どれも無ければ null (呼び出し側で汎用文言)。
export function extractLlmErrorDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail || null
  if (detail && typeof detail === 'object') {
    const o = detail as Record<string, unknown>
    if (typeof o.error === 'string' && o.error) return o.error
    if (typeof o.code === 'string' && o.code) return o.code
    if (typeof o.message === 'string' && o.message) return o.message
  }
  return null
}

export function getLlmConfig() {
  return apiGet<LlmConfig>('/llm/config')
}

// ピッカー用のチャットモデル一覧 + 既定 ID。backend は {success, data:{models, default}}
// 形で返すため data を取り出して返す。
export async function getLlmModels(): Promise<{ models: LlmModel[]; default: string }> {
  const r = await apiGet<{ success: boolean; data: { models: LlmModel[]; default: string } }>(
    '/llm/models',
  )
  return r.data
}

export function listConversations() {
  return apiGet<{ conversations: LlmConversation[] }>('/llm/conversations')
}

export function createConversation(body: { title?: string; system_prompt?: string } = {}) {
  return apiPost<LlmConversation>('/llm/conversations', body)
}

export function renameConversation(id: number, title: string) {
  return apiPatch<LlmConversation>(`/llm/conversations/${id}`, { title })
}

export function deleteConversation(id: number) {
  return apiDelete<{ success: boolean }>(`/llm/conversations/${id}`)
}

export function getMessages(id: number) {
  return apiGet<{ messages: LlmMessage[] }>(`/llm/conversations/${id}/messages`)
}

// SSE ストリーミング送信。data: {json}\n\n を逐次パースして onEvent に流す。
// model: ピッカーで選んだモデル ID (backend の MessageCreate.model)。allowlist 検証は
// backend 側 (allowlist 外は 422)。reasoning 表示はモデルが reasoning_content を出すと自動。
export async function streamMessage(
  conversationId: number,
  content: string,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
  model?: string,
  images: string[] = [],
): Promise<void> {
  let resp: Response
  try {
    // body: content は必須。model / images は値がある時のみ含める (省略時は backend の既定)。
    const payload: { content: string; model?: string; images?: string[] } = { content }
    if (model) payload.model = model
    if (images.length > 0) payload.images = images
    // 共通の refresh-aware 経路: access token 期限切れ (401) は single-flight refresh 後に 1 回だけ再送する。
    // 認可失敗は生成開始前に返るため、再送で二重生成にはならない。
    resp = await fetchAuthed(`${API_BASE_URL}/llm/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (e) {
    onEvent({ type: 'error', message: 'network error' })
    return
  }
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`
    try {
      const j = await resp.json()
      // detail が object のとき String() すると "[object Object]" になるため、安定コードを取り出す。
      const d = extractLlmErrorDetail(j?.detail)
      if (d) msg = d
    } catch {
      /* ignore */
    }
    onEvent({ type: 'error', message: msg })
    return
  }
  const reader = resp.body?.getReader()
  if (!reader) {
    onEvent({ type: 'error', message: 'no stream body' })
    return
  }
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!chunk.startsWith('data:')) continue
      const payload = chunk.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload) as StreamEvent)
      } catch {
        /* 不正な行は無視 */
      }
    }
  }
}
