// 汎用 LLM チャット (/#/llm) の API クライアント。
// 会話 CRUD は通常の apiGet/apiPost、メッセージ送信のみ SSE ストリーミングを生 fetch で扱う。
import { API_BASE_URL, apiGet, apiPost, apiPatch, apiDelete } from './client'

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

// client.ts の authHeaders と同等 (token 優先、無ければ X-Role フォールバック)。
function authHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  try {
    const token = sessionStorage.getItem('shuttlescope_token')
    if (token) {
      h['Authorization'] = `Bearer ${token}`
    } else {
      const role = sessionStorage.getItem('shuttlescope_role')
      const pid = sessionStorage.getItem('shuttlescope_player_id')
      const team = sessionStorage.getItem('shuttlescope_team_name')
      if (role) h['X-Role'] = role
      if (pid) h['X-Player-Id'] = pid
      if (team) h['X-Team-Name'] = encodeURIComponent(team)
    }
  } catch {
    /* ignore */
  }
  return h
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
    resp = await fetch(`${API_BASE_URL}/llm/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
      if (j && j.detail) msg = String(j.detail)
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
