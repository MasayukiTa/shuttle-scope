/**
 * ライブ推論オーバーレイ
 * video 要素の上に TrackNet 推論結果のゾーン / 信頼度をオーバーレイ表示する。
 * DeviceManagerPanel や AnnotatorPage の live camera preview に重ねて使う。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLiveInference } from '@/hooks/useLiveInference'
import type { LiveInferenceCandidate } from '@/types'
import { MIcon } from '@/components/common/MIcon'

interface Props {
  videoRef: React.RefObject<HTMLVideoElement>
  sessionCode: string | null
  className?: string
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? 'bg-[var(--ss-success)]' : pct >= 40 ? 'bg-[var(--ss-warn)]' : 'bg-[var(--ss-bad)]'
  return (
    <div className="flex items-center gap-1">
      <div className="flex-1 h-1 bg-[var(--ss-surface-3)] rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-[var(--ss-t3)] w-7">{pct}%</span>
    </div>
  )
}

// NOTE: per-frame overlay マーカー — リアルタイム描画要素なので新規 transition は追加しない。
function ZoneMarker({ candidate }: { candidate: LiveInferenceCandidate }) {
  if (!candidate.zone || !candidate.x_norm || !candidate.y_norm) return null
  const x = candidate.x_norm * 100
  const y = candidate.y_norm * 100
  return (
    <div
      className="absolute pointer-events-none"
      style={{ left: `${x}%`, top: `${y}%`, transform: 'translate(-50%, -50%)' }}
    >
      <div className="w-5 h-5 rounded-full border-2 border-yellow-400 bg-yellow-400/20 animate-ping absolute" />
      <div className="w-5 h-5 rounded-full border-2 border-yellow-400 bg-yellow-400/20 relative" />
    </div>
  )
}

export function LiveInferenceOverlay({ videoRef, sessionCode, className = '' }: Props) {
  const { t } = useTranslation()
  const [enabled, setEnabled] = useState(false)
  const { candidate, inferring } = useLiveInference(videoRef, sessionCode, enabled)

  return (
    <div className={className}>
      {/* ゾーンマーカーオーバーレイ */}
      {enabled && candidate && (
        <div className="absolute inset-0 pointer-events-none z-10">
          <ZoneMarker candidate={candidate} />
        </div>
      )}

      {/* コントロールパネル（左上隅 — 右上のTrash2と被らないよう左側に配置） */}
      <div className="absolute top-2 left-2 z-20 flex flex-col items-start gap-1.5">
        {/* 推論オン/オフトグル */}
        <button
          onClick={() => setEnabled((v) => !v)}
          className={`flex items-center gap-1 px-2 py-1 rounded-ss-sm text-[10px] font-medium transition-colors duration-base ease-out border ${
            enabled
              ? 'bg-[var(--ss-brand)] text-white border-transparent hover:bg-[var(--ss-brand-hover)]'
              : 'bg-black/70 border-[var(--ss-border-strong)] hover:bg-black/85 text-white'
          }`}
        >
          {enabled ? <MIcon name="bolt" size={10} /> : <MIcon name="flash_off" size={10} />}
          <span>
            {enabled ? t('live_inference.enabled') : t('live_inference.disabled')}
          </span>
        </button>

        {/* 推論結果表示 */}
        {enabled && (
          <div className="bg-black/80 rounded-ss-sm px-2 py-1.5 min-w-24">
            {!candidate || !candidate.available ? (
              <p className="text-[9px] text-white/60">
                {inferring
                  ? t('live_inference.buffering')
                  : t('live_inference.model_unavailable')}
              </p>
            ) : candidate.buffering ? (
              <p className="text-[9px] text-[var(--ss-warn)]">{t('live_inference.buffering')}</p>
            ) : (
              <>
                <p className="text-[9px] text-white/60 mb-0.5">{t('live_inference.candidate_zone')}</p>
                <p className="text-xs font-mono text-white mb-0.5">
                  {candidate.zone ?? t('live_inference.no_candidate')}
                </p>
                <ConfidenceBar value={candidate.confidence} />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
