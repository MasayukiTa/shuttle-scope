/**
 * ライブソース選択 UI
 * セッション内の登録済みソース一覧（優先度順）を表示し、
 * アクティブ化 / 停止 / ローカルカメラ登録 を行う。
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { apiGet, apiPost } from '@/api/client'
import type { LiveSource } from '@/types'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  sessionCode: string
}

// ─── ソース種別アイコン ───────────────────────────────────────────────────────

function SourceIcon({ kind }: { kind: string }) {

  const cls = 'w-4 h-4 flex-shrink-0'
  switch (kind) {
    case 'iphone_webrtc': return <MIcon name="smartphone" className={cls} />
    case 'ipad_webrtc':   return <MIcon name="tablet" className={cls} />
    case 'usb_camera':    return <MIcon name="usb" className={cls} />
    case 'builtin_camera': return <MIcon name="photo_camera" className={cls} />
    default:              return <MIcon name="monitor" className={cls} />
  }
}

// ─── 適合性バッジ ─────────────────────────────────────────────────────────────

function SuitabilityBadge({ value }: { value: string }) {

  const color = value === 'high' ? 'bg-[var(--ss-success)] text-white'
    : value === 'usable' ? 'bg-[var(--ss-warn)] text-white'
    : 'bg-[var(--ss-surface-3)] text-[var(--ss-t2)]'
  const labelMap: Record<string, string> = {
    high: '推奨', usable: '使用可', fallback: 'フォールバック',
  }
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded-ss-pill font-medium ${color}`}>
      {labelMap[value] ?? value}
    </span>
  )
}

// ─── ソース状態バッジ ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation()

  if (status === 'active') {
    return (
      <span className="flex items-center gap-0.5 text-[9px] text-[var(--ss-bad)] font-medium">
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--ss-bad)] animate-pulse" />
        {t('auto.LiveSourceSelector.active')}
      </span>
    )
  }
  if (status === 'candidate') {
    return <span className="text-[9px] text-[var(--ss-warn)]">{t('auto.LiveSourceSelector.k1')}</span>
  }
  return <span className="text-[9px] text-[var(--ss-t3)]">{t('auto.LiveSourceSelector.k2')}</span>
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

  const _handleRegisterLocal = async (deviceId: string, label: string) => {
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

  // NOTE: トークンはテーマに応じて自動的に切り替わるため isLight 分岐は不要だが、
  // フック呼び出し (テーマ変更時の再レンダリングトリガー) は維持する。
  const titleColor = 'text-[var(--ss-t1)]'
  const subColor = 'text-[var(--ss-t3)]'
  const rowBg = 'bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)]'

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className={`text-xs font-medium ${titleColor}`}>{t('live_source.title')}</p>
        <button onClick={fetchSources} className="text-[var(--ss-t3)] hover:text-[var(--ss-t1)]">
          <MIcon name="refresh" size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {sources.length === 0 ? (
        <p className={`text-[10px] text-center py-3 ${subColor}`}>{t('live_source.no_sources')}</p>
      ) : (
        <div className="space-y-1.5">
          {sources.map((src) => (
            <div key={src.id} className={`rounded-ss-md px-3 py-2.5 ${rowBg}`}>
              <div className="flex items-start gap-2">
                <div className={`mt-0.5 ${subColor}`}>
                  <SourceIcon kind={src.source_kind} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`text-xs font-medium truncate ${titleColor}`}>
                      {t(`live_source.source_kind_${src.source_kind}` as Parameters<typeof t>[0], src.source_kind)}
                    </span>
                    <SuitabilityBadge value={src.suitability} />
                    <StatusBadge status={src.source_status} />
                  </div>
                  <div className={`flex items-center gap-2 mt-0.5 text-[10px] ${subColor}`}>
                    {src.source_priority <= 2 && (
                      <span className="flex items-center gap-0.5">
                        <MIcon name="star" size={9} />
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
                      className="text-[10px] px-2 py-1 rounded-ss-md bg-[var(--ss-surface-1)] border border-[var(--ss-border-strong)] text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]"
                    >
                      {t('live_source.deactivate')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleActivate(src)}
                      className="text-[10px] px-2 py-1 rounded-ss-md bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white"
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
