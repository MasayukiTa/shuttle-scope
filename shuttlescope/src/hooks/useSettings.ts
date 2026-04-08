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
  tracknet_backend: 'auto' | 'tensorflow_cpu' | 'openvino' | 'onnx_cpu'
  tracknet_mode: 'batch' | 'assist'
  tracknet_max_cpu_pct: number
  video_source_mode: VideoSourceMode
  // データ同期設定
  sync_device_id: string
  sync_folder_path: string
}

const DEFAULTS: AppSettings = {
  tracknet_enabled: false,
  tracknet_backend: 'auto',
  tracknet_mode: 'batch',
  tracknet_max_cpu_pct: 50,
  video_source_mode: 'local',
  sync_device_id: '',
  sync_folder_path: '',
}

const LS_KEY = 'shuttlescope.settings'

function loadLocal(): AppSettings {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {}
  return { ...DEFAULTS }
}

function saveLocal(s: AppSettings) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(s))
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
