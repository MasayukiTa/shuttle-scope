// ベンチマーク API クライアント
// /api/v1/benchmark/* エンドポイントへのリクエスト関数と型定義

import { apiGet, apiPost } from '@/api/client'

// ─── 型定義 ──────────────────────────────────────────────────────────────────

/** デバイス種別 */
export type DeviceType = 'cpu' | 'igpu' | 'dgpu' | 'ray_worker'

/** バックエンド計算デバイス情報 */
export interface ComputeDevice {
  device_id: string
  label: string
  device_type: DeviceType
  backend: string
  available: boolean
  specs: Record<string, string | number>
}

/** ベンチマーク対象ターゲット */
export type BenchmarkTarget =
  | 'tracknet'
  | 'pose'
  | 'pipeline_full'
  | 'clip_extract'
  | 'statistics'

/** 単一ターゲットの計測結果（成功またはエラー） */
export type BenchmarkResult =
  | { fps: number; avg_ms: number; p95_ms: number }
  | { error: string }

/** ジョブステータス */
export type BenchmarkJobStatus = 'queued' | 'running' | 'done' | 'failed'

/** ジョブ全体のレスポンス */
export interface BenchmarkJob {
  job_id: string
  status: BenchmarkJobStatus
  progress: number
  results: {
    [device_id: string]: {
      [target: string]: BenchmarkResult
    }
  }
}

// ─── API 関数 ─────────────────────────────────────────────────────────────────

/** 利用可能なデバイス一覧を取得する */
export function getDevices(): Promise<ComputeDevice[]> {
  return apiGet<ComputeDevice[]>('/v1/benchmark/devices')
}

/** ベンチマークジョブを開始し job_id を返す */
export async function runBenchmark(
  device_ids: string[],
  targets: BenchmarkTarget[],
  n_frames: number,
): Promise<string> {
  const res = await apiPost<{ job_id: string }>('/v1/benchmark/run', {
    device_ids,
    targets,
    n_frames,
  })
  return res.job_id
}

/** ジョブの進捗・結果を取得する */
export function getJob(job_id: string): Promise<BenchmarkJob> {
  return apiGet<BenchmarkJob>(`/v1/benchmark/jobs/${job_id}`)
}

/** 実行中のジョブをキャンセルする */
export async function cancelJob(job_id: string): Promise<void> {
  await fetch(`/api/v1/benchmark/jobs/${job_id}`, { method: 'DELETE' })
}
