import { useEffect, useCallback } from 'react'
import { useAnnotationStore } from '@/store/annotationStore'
import { KEYBOARD_MAP } from '@/components/annotation/ShotTypePanel'
import { ShotType } from '@/types'

interface UseKeyboardOptions {
  videoRef?: React.RefObject<HTMLVideoElement>
  enabled?: boolean
}

/**
 * キーボードショートカット一元管理フック
 *
 * 2アクションフロー:
 *   ショットキー(s/c/p…) → 着地ゾーンクリック → 自動確定
 *
 * Space     : 再生 / 一時停止
 * ←/→       : 1フレーム移動 (30fps想定)
 * Shift+←/→ : 10秒スキップ
 * s,c,p…   : ショット種別入力 (idle / land_zone どちらでも有効)
 * Tab       : プレイヤー切替 (A ↔ B)
 * Enter     : ラリー終了確認画面へ
 * Ctrl+Z    : アンドゥ（直前ストローク削除）
 * Escape    : キャンセル (rally_end → idle, land_zone → idle)
 */
export function useKeyboard({ videoRef, enabled = true }: UseKeyboardOptions = {}) {
  const store = useAnnotationStore()

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      const { inputStep, isRallyActive, currentStrokes } = store

      // --- 動画シーク（常時有効） ---
      if (e.shiftKey && e.key === 'ArrowLeft') {
        e.preventDefault()
        if (videoRef?.current)
          videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 10)
        return
      }
      if (e.shiftKey && e.key === 'ArrowRight') {
        e.preventDefault()
        if (videoRef?.current)
          videoRef.current.currentTime = Math.min(
            videoRef.current.duration ?? 0,
            videoRef.current.currentTime + 10
          )
        return
      }
      if (e.key === 'ArrowLeft' && !e.shiftKey) {
        e.preventDefault()
        if (videoRef?.current)
          videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 1 / 30)
        return
      }
      if (e.key === 'ArrowRight' && !e.shiftKey) {
        e.preventDefault()
        if (videoRef?.current)
          videoRef.current.currentTime = Math.min(
            videoRef.current.duration ?? 0,
            videoRef.current.currentTime + 1 / 30
          )
        return
      }

      // Space: 再生/一時停止（ラリー管理には使わない）
      if (e.key === ' ') {
        e.preventDefault()
        const v = videoRef?.current
        if (!v) return
        if (v.paused) {
          v.play()
        } else {
          v.pause()
        }
        return
      }

      // Tab: プレイヤー切替
      if (e.key === 'Tab') {
        e.preventDefault()
        store.togglePlayer()
        return
      }

      // Ctrl+Z: アンドゥ
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault()
        store.undoLastStroke()
        return
      }

      // Escape: キャンセル
      if (e.key === 'Escape') {
        e.preventDefault()
        store.cancelRallyEnd()
        return
      }

      // Enter: ラリー終了確認へ
      if (e.key === 'Enter') {
        e.preventDefault()
        if (isRallyActive && currentStrokes.length > 0 && inputStep !== 'rally_end') {
          store.endRallyRequest()
        }
        return
      }

      // ショット種別キー (idle / land_zone 時に有効)
      // Ctrl/Meta/Alt との組み合わせは除外
      if ((inputStep === 'idle' || inputStep === 'land_zone') && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const key = e.key.toLowerCase()
        const shotType = KEYBOARD_MAP[key] as ShotType | undefined
        if (shotType) {
          e.preventDefault()
          // 再生中のみ一時停止（その瞬間を記録するため）
          // 停止中 → 再生はしない（誤操作を防ぐ）
          const v = videoRef?.current
          if (v && !v.paused) v.pause()
          const currentSec = v?.currentTime ?? 0
          store.inputShotType(shotType, currentSec)
          return
        }
      }
    },
    [enabled, store, videoRef]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}
