/**
 * ライブソース選択 UI
 * セッション内の登録済みソース一覧（優先度順）を表示し、
 * アクティブ化 / 停止 / ローカルカメラ登録 を行う。
 */
import { useCallback, useEffect, useState } from 'react'
import { Camera, Smartphone, Tablet, Usb, Monitor, Star, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { apiGet, apiPost } from '@/api/client'
import type { LiveSource } from '@/types'

interface Props {
  sessionCode: string
}

// ─── ソース種別アイコン ───────────────────────────────────────────────────────

function SourceIcon({ kind }: { kind: string }) {
  const cls = 'w-4 h-4 flex-shrink-0'
  switch (kind) {
    case 'iphone_webrtc': return <Smartphone className={cls} />
    case 'ipad_webrtc':   return <Tablet className={cls} />
    case 'usb_camera':    return <Usb className={cls} />
    case 'builtin_camera': return <Camera className={cls} />
    default:              return <Monitor className={cls} />
  }
}

// ─── 適合性バッジ ─────────────────────────────────────────────────────────────

function SuitabilityBadge({ value }: { value: string }) {
  const color = value === 'high' ? 'bg-green-600 text-white'
    : value === 'usable' ? 'bg-yellow-600 text-white'
    : 'bg-gray-600 text-gray-300'
  const labelMap: Record<string, string> = {
    high: '推奨', usable: '使用可', fallback: 'フォールバック',
  }
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${color}`}>
      {labelMap[value] ?? value}
    </span>
  )
}

// ─── ソース状態バッジ ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === 'active') {
    return (
      <span className="flex items-center gap-0.5 text-[9px] text-red-400 font-medium">
        <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
        アクティブ
      </span>
    )
  }
  if (status === 'candidate') {
    return <span className="text-[9px] text-yellow-400">候補</span>
  }
  return <span className="text-[9px] text-gray-500">待機</span>
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────

export function LiveSourceSelector({ sessionCode }: Props) {
  const { t } = useTranslation()
  const isLight = useIsLightMode()
  const [sources, setSources] = useState<LiveSource[]>([])
  const [loading, setLoading] = useState(false)

  const fetchSources = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiGet<{ success: boolean; data: LiveSource[] }>(`/sessions/${sessionCode}/sources`)
      if (res.success) setSources(res.data)
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [sessionCode])

  useEffect(() => {
    fetchSources()
  }, [fetchSources])

  const handleActivate = async (source: LiveSource) => {
    try {
      await apiPost(`/sessions/${sessionCode}/sources/${source.id}/activate`, {})
      fetchSources()
    } catch { /* ignore */ }
  }

  const handleDeactivate = async (source: LiveSource) => {
    try {
      await apiPost(`/sessions/${sessionCode}/sources/${source.id}/deactivate`, {})
      fetchSources()
    } catch { /* ignore */ }
  }

  const handleRegisterLocal = async (deviceId: string, label: string) => {
    // USB / 内蔵カメラを候補ソースとして登録
    const isUsb = label.toLowerCase().includes('usb')
    const kind = isUsb ? 'usb_camera' : 'builtin_camera'
    try {
      await apiPost(`/sessions/${sessionCode}/sources`, {
        source_kind: kind,
        source_resolution: '1280x720',
        source_fps: 30,
      })
      fetchSources()
    } catch { /* ignore */ }
  }

  const titleColor = isLight ? 'text-gray-900' : 'text-white'
  const subColor = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowBg = isLight ? 'bg-gray-50 hover:bg-gray-100' : 'bg-gray-700/50 hover:bg-gray-700'

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className={`text-xs font-medium ${titleColor}`}>{t('live_source.title')}</p>
        <button onClick={fetchSources} className={`${subColor} hover:${titleColor}`}>
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {sources.length === 0 ? (
        <p className={`text-[10px] text-center py-3 ${subColor}`}>{t('live_source.no_sources')}</p>
      ) : (
        <div className="space-y-1.5">
          {sources.map((src) => (
            <div key={src.id} className={`rounded-lg px-3 py-2.5 ${rowBg}`}>
              <div className="flex items-start gap-2">
                <div className={`mt-0.5 ${subColor}`}>
                  <SourceIcon kind={src.source_kind} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`text-xs font-medium truncate ${titleColor}`}>
                      {t(`live_source.source_kind_${src.source_kind}` as any, src.source_kind)}
                    </span>
                    <SuitabilityBadge value={src.suitability} />
                    <StatusBadge status={src.source_status} />
                  </div>
                  <div className={`flex items-center gap-2 mt-0.5 text-[10px] ${subColor}`}>
                    {src.source_priority <= 2 && (
                      <span className="flex items-center gap-0.5">
                        <Star size={9} />
                        {t('live_source.priority_label')} {src.source_priority}
                      </span>
                    )}
                    {src.source_resolution && (
                      <span>{src.source_resolution}</span>
                    )}
                    {src.source_fps && (
                      <span>{src.source_fps} {t('live_source.fps_label')}</span>
                    )}
                  </div>
                </div>
                {/* アクション */}
                <div className="flex-shrink-0">
                  {src.source_status === 'active' ? (
                    <button
                      onClick={() => handleDeactivate(src)}
                      className="text-[10px] px-2 py-1 rounded bg-gray-600 hover:bg-gray-500 text-white"
                    >
                      {t('live_source.deactivate')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleActivate(src)}
                      className="text-[10px] px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white"
                    >
                      {t('live_source.activate')}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
