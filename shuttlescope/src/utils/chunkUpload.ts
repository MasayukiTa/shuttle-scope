/**
 * 分割動画アップロード (ブラウザ用)
 *
 * - File を chunkSize byte ごとに区切って順次 POST
 * - throttleMbps で帯域を制限 (Cloudflare Free の帯域配慮)
 * - 中断・再開対応: upload_id + match_id を localStorage に保存し、
 *   既に受領済みチャンクは status エンドポイントからの received_indices でスキップ
 * - onProgress: 0〜1 の進捗
 */
import { API_BASE_URL, getAuthHeaders } from '@/api/client'

export interface ChunkUploadOptions {
  file: File
  matchId?: number
  chunkSize?: number        // bytes. 既定 2MB
  throttleMbps?: number     // クライアント送信上限帯域. 既定 16Mbps
  maxRetriesPerChunk?: number // 既定 5
  signal?: AbortSignal
  onProgress?: (p: { sent: number; total: number; ratio: number; mbps: number }) => void
  onUploadIdAssigned?: (uploadId: string) => void
}

export interface ChunkUploadResult {
  uploadId: string
  finalPath: string
  matchId?: number | null
}

const DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024
const DEFAULT_THROTTLE_MBPS = 16
const DEFAULT_MAX_RETRIES = 5

const STORAGE_KEY = 'shuttlescope.chunkUpload.inflight'

interface InflightRecord {
  uploadId: string
  matchId?: number
  fileSize: number
  fileName: string
  chunkSize: number
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    if (signal) {
      const onAbort = () => {
        clearTimeout(t)
        reject(new DOMException('Aborted', 'AbortError'))
      }
      if (signal.aborted) onAbort()
      else signal.addEventListener('abort', onAbort, { once: true })
    }
  })
}

function loadInflight(key: string): InflightRecord | null {
  try {
    const raw = localStorage.getItem(`${STORAGE_KEY}:${key}`)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
function saveInflight(key: string, rec: InflightRecord): void {
  try {
    localStorage.setItem(`${STORAGE_KEY}:${key}`, JSON.stringify(rec))
  } catch {
    // quota 満杯は致命的でないので無視
  }
}
function clearInflight(key: string): void {
  try {
    localStorage.removeItem(`${STORAGE_KEY}:${key}`)
  } catch {}
}

function inflightKey(file: File, matchId?: number): string {
  // file.name + file.size + file.lastModified + matchId でユニーク識別
  return `${matchId ?? 'none'}|${file.name}|${file.size}|${file.lastModified}`
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`POST ${path} failed: ${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: getAuthHeaders(),
    signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`GET ${path} failed: ${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

export async function uploadVideoInChunks(opts: ChunkUploadOptions): Promise<ChunkUploadResult> {
  const {
    file,
    matchId,
    chunkSize = DEFAULT_CHUNK_SIZE,
    throttleMbps = DEFAULT_THROTTLE_MBPS,
    maxRetriesPerChunk = DEFAULT_MAX_RETRIES,
    signal,
    onProgress,
    onUploadIdAssigned,
  } = opts

  const key = inflightKey(file, matchId)

  // ── 既存 inflight があれば再利用、無ければ init ──
  let uploadId: string | null = null
  let effectiveChunkSize = chunkSize
  let totalChunks = 0
  let receivedIndices = new Set<number>()

  const prev = loadInflight(key)
  if (prev) {
    try {
      const status = await getJson<{
        upload_id: string
        status: string
        received_count: number
        total_chunks: number
        received_indices: number[]
      }>(`/v1/uploads/video/${prev.uploadId}/status`, signal)
      if (status.status === 'uploading') {
        uploadId = prev.uploadId
        effectiveChunkSize = prev.chunkSize
        totalChunks = status.total_chunks
        receivedIndices = new Set(status.received_indices)
      } else {
        clearInflight(key)
      }
    } catch {
      // サーバ側で消えていた → init やり直し
      clearInflight(key)
    }
  }

  if (!uploadId) {
    const init = await postJson<{
      upload_id: string
      chunk_size: number
      total_chunks: number
      received_indices: number[]
    }>('/v1/uploads/video/init', {
      match_id: matchId,
      filename: file.name,
      total_size: file.size,
      chunk_size: chunkSize,
      mime_type: file.type || null,
    }, signal)
    uploadId = init.upload_id
    effectiveChunkSize = init.chunk_size
    totalChunks = init.total_chunks
    receivedIndices = new Set(init.received_indices)
    saveInflight(key, {
      uploadId,
      matchId,
      fileSize: file.size,
      fileName: file.name,
      chunkSize: effectiveChunkSize,
    })
    onUploadIdAssigned?.(uploadId)
  } else {
    onUploadIdAssigned?.(uploadId)
  }

  // ── チャンクを順次送信 ──
  const throttleBytesPerSec = (throttleMbps * 1000 * 1000) / 8
  let sentBytes = receivedIndices.size * effectiveChunkSize
  const startTs = performance.now()

  for (let i = 0; i < totalChunks; i++) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (receivedIndices.has(i)) continue

    const start = i * effectiveChunkSize
    const end = Math.min(start + effectiveChunkSize, file.size)
    const blob = file.slice(start, end)

    const form = new FormData()
    form.append('upload_id', uploadId)
    form.append('chunk_index', String(i))
    form.append('chunk', blob, `${i}.bin`)

    let lastErr: unknown = null
    for (let attempt = 0; attempt < maxRetriesPerChunk; attempt++) {
      try {
        const chunkStartTs = performance.now()
        const res = await fetch(`${API_BASE_URL}/v1/uploads/video/chunk`, {
          method: 'POST',
          headers: getAuthHeaders(),
          body: form,
          signal,
        })
        if (!res.ok) {
          const text = await res.text().catch(() => '')
          // 400-499 は再送無意味（冪等性違反/権限/サイズ）
          if (res.status >= 400 && res.status < 500 && res.status !== 429) {
            throw new Error(`chunk ${i} failed: ${res.status} ${text}`)
          }
          throw new Error(`chunk ${i} transient ${res.status} ${text}`)
        }
        await res.json()
        sentBytes += end - start

        // 帯域スロットリング: 経過時間がアップロード想定時間より短ければ sleep
        const elapsedSec = (performance.now() - startTs) / 1000
        const expectedSec = sentBytes / throttleBytesPerSec
        if (expectedSec > elapsedSec) {
          await sleep((expectedSec - elapsedSec) * 1000, signal)
        }

        // 進捗通知
        if (onProgress) {
          const nowElapsed = Math.max(0.001, (performance.now() - startTs) / 1000)
          const mbps = (sentBytes * 8) / (nowElapsed * 1000 * 1000)
          onProgress({
            sent: sentBytes,
            total: file.size,
            ratio: Math.min(1, sentBytes / file.size),
            mbps,
          })
        }
        lastErr = null
        break
      } catch (e) {
        if (signal?.aborted) throw e
        lastErr = e
        // 指数バックオフ（ジッタ付き）
        const backoff = Math.min(30000, 500 * Math.pow(2, attempt)) + Math.random() * 300
        await sleep(backoff, signal)
      }
    }
    if (lastErr) throw lastErr
  }

  // ── finalize ──
  const final = await postJson<{
    upload_id: string
    status: string
    final_path: string
    match_id: number | null
  }>(`/v1/uploads/video/${uploadId}/finalize`, {}, signal)

  clearInflight(key)

  return {
    uploadId,
    finalPath: final.final_path,
    matchId: final.match_id,
  }
}

export async function abortChunkUpload(uploadId: string): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/v1/uploads/video/${uploadId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    })
  } catch {
    // best effort
  }
}
