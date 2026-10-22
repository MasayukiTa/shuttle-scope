/**
 * アプリ設定の読み書きフック。
 * P2/TX-2: まず localStorage に保存し、バックエンドAPIにも同期。
 * バックエンドが未起動の場合は localStorage のみで動作する。
 */
import { useState, useEffect, useCallback } from 'react'
import { apiGet, apiPut } from '@/api/client'
import type { VideoSourceMode } from '@/types'

export interface AppSettings {
  tracknet_enabled: boolean
  tracknet_backend: 'auto' | 'cuda' | 'onnx_cuda' | 'directml' | 'tensorflow_cpu' | 'openvino' | 'onnx_cpu'
  tracknet_mode: 'batch' | 'assist'
  tracknet_max_cpu_pct: number
  // GPU / デバイス設定
  cuda_device_index: number
  openvino_device: string
  yolo_backend: 'auto' | 'openvino' | 'ultralytics' | 'onnx_cpu'
  // YOLO プレイヤー検出
  yolo_enabled: boolean
  video_source_mode: VideoSourceMode
  // データ同期設定
  sync_device_id: string
  sync_folder_path: string
  // リモートトンネル設定
  tunnel_provider: 'auto' | 'cloudflare' | 'ngrok'
  ngrok_authtoken: string
  // リモート映像（WebRTC）設定
  video_transport: 'off' | 'webrtc'
  turn_enabled: boolean
  turn_url: string
  turn_username: string
  turn_credential: string
  turn_static_auth_secret: string
}

const DEFAULTS: AppSettings = {
  tracknet_enabled: true,
  tracknet_backend: 'auto',
  tracknet_mode: 'batch',
  tracknet_max_cpu_pct: 50,
  cuda_device_index: 0,
  openvino_device: 'GPU',
  yolo_backend: 'auto',
  yolo_enabled: true,
  video_source_mode: 'local',
  sync_device_id: '',
  sync_folder_path: '',
  tunnel_provider: 'auto',
  ngrok_authtoken: '',
  video_transport: 'off',
  turn_enabled: false,
  turn_url: '',
  turn_username: '',
  turn_credential: '',
  turn_static_auth_secret: '',
}

const LS_KEY = 'shuttlescope.settings'

// ngrok / TURN の資格情報はブラウザの localStorage に残さない。
// 共有 PC ではログアウト後も次の利用者が読め、XSS の窃取対象にもなるため。
// 値は admin が /settings から取得した分を画面のメモリ上でだけ持つ。
const SECRET_KEYS = [
  'ngrok_authtoken',
  'turn_url',
  'turn_username',
  'turn_credential',
  'turn_static_auth_secret',
] as const

function stripSecrets<T extends Partial<AppSettings>>(s: T): T {
  const out: Record<string, unknown> = { ...s }
  for (const k of SECRET_KEYS) delete out[k]
  return out as T
}

function loadLocal(): AppSettings {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) {
      const stored = JSON.parse(raw) as Partial<AppSettings>
      // 旧版が保存した資格情報が残っていれば、読み込み時に消す
      if (SECRET_KEYS.some((k) => k in stored)) {
        localStorage.setItem(LS_KEY, JSON.stringify(stripSecrets(stored)))
      }
      return { ...DEFAULTS, ...stripSecrets(stored) }
    }
  } catch {}
  return { ...DEFAULTS }
}

function saveLocal(s: AppSettings) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(stripSecrets(s)))
  } catch {}
}

export function useSettings() {
  const [settings, setSettingsState] = useState<AppSettings>(loadLocal)
  const [loading, setLoading] = useState(false)

  // 初回マウント時にバックエンドから最新設定を取得
  useEffect(() => {
    apiGet<{ success: boolean; data: Record<string, unknown> }>('/settings')
      .then((res) => {
        if (res.success) {
          const merged = { ...DEFAULTS, ...(res.data as Partial<AppSettings>) }
          setSettingsState(merged)
          saveLocal(merged)
        }
      })
      .catch(() => {/* バックエンド未起動時はlocalStorageで動作 */})
  }, [])

  const updateSettings = useCallback(async (partial: Partial<AppSettings>) => {
    const next = { ...settings, ...partial }
    setSettingsState(next)
    saveLocal(next)
    setLoading(true)
    try {
      await apiPut('/settings', { settings: partial })
    } catch {
      // バックエンド未起動時はlocalStorageのみで動作
    } finally {
      setLoading(false)
    }
  }, [settings])

  return { settings, updateSettings, loading }
}
