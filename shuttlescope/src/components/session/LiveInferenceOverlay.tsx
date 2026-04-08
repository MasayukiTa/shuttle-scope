/**
 * ライブ推論オーバーレイ
 * video 要素の上に TrackNet 推論結果のゾーン / 信頼度をオーバーレイ表示する。
 * DeviceManagerPanel や AnnotatorPage の live camera preview に重ねて使う。
 */
import { useState } from 'react'
import { Zap, ZapOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLiveInference } from '@/hooks/useLiveInference'
import type { LiveInferenceCandidate } from '@/types'

interface Props {
  videoRef: React.RefObject<HTMLVideoElement>
  sessionCode: string | null
  className?: string
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-1">
      <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-gray-400 w-7">{pct}%</span>
    </div>
  )
}

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
    <div className={`relative ${className}`}>
      {/* ゾーンマーカーオーバーレイ */}
      {enabled && candidate && (
        <div className="absolute inset-0 pointer-events-none z-10">
          <ZoneMarker candidate={candidate} />
        </div>
      )}

      {/* コントロールパネル（右上隅） */}
      <div className="absolute top-2 right-2 z-20 flex flex-col items-end gap-1.5">
        {/* 推論オン/オフトグル */}
        <button
          onClick={() => setEnabled((v) => !v)}
          className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${
            enabled
              ? 'bg-yellow-500 text-black hover:bg-yellow-400'
              : 'bg-gray-800/80 text-gray-400 hover:bg-gray-700/80'
          }`}
        >
          {enabled ? <Zap size={10} /> : <ZapOff size={10} />}
          {enabled ? t('live_inference.enabled') : t('live_inference.disabled')}
        </button>

        {/* 推論結果表示 */}
        {enabled && (
          <div className="bg-gray-900/80 rounded px-2 py-1.5 min-w-24">
            {!candidate || !candidate.available ? (
              <p className="text-[9px] text-gray-500">
                {inferring
                  ? t('live_inference.buffering')
                  : t('live_inference.model_unavailable')}
              </p>
            ) : candidate.buffering ? (
              <p className="text-[9px] text-yellow-400">{t('live_inference.buffering')}</p>
            ) : (
              <>
                <p className="text-[9px] text-gray-400 mb-0.5">{t('live_inference.candidate_zone')}</p>
                <p className="text-xs font-mono text-yellow-300 mb-0.5">
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
