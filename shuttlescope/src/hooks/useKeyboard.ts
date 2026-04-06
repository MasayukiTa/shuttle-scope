import { useEffect, useCallback } from 'react'
import { useAnnotationStore } from '@/store/annotationStore'
import { KEYBOARD_MAP } from '@/components/annotation/ShotTypePanel'
import { ShotType, Zone9 } from '@/types'

interface UseKeyboardOptions {
  videoRef?: React.RefObject<HTMLVideoElement>
  enabled?: boolean
  /** K-001: マッチデーモード用 1–5 キーでエンドタイプ選択（cant_reach 削除後は5種類） */
  onEndTypeSelect?: (endType: string) => void
}

/**
 * キーボードショートカット一元管理フック
 *
 * ─── 入力フロー ──────────────────────────────────────────────────────────────
 *  ショットキー(s/c/p…) → テンキー1-9で落点 or テンキー0でスキップ → 自動確定
 *
 * ─── テンキーマッピング ───────────────────────────────────────────────────────
 *  コート配置とテンキー物理配列が一致（バック上・ネット下）:
 *    Numpad7=BL  Numpad8=BC  Numpad9=BR
 *    Numpad4=ML  Numpad5=MC  Numpad6=MR
 *    Numpad1=NL  Numpad2=NC  Numpad3=NR
 *    Numpad0 / NumpadDecimal / NumpadEnter = スキップ（落点なし）
 *
 * ─── 属性テンキー ─────────────────────────────────────────────────────────────
 *    Numpad/ = バックハンドトグル
 *    Numpad* = ラウンドヘッドトグル
 *    Numpad- = ネット上下サイクル（未指定→上→下→未指定）
 *
 * ─── その他 ──────────────────────────────────────────────────────────────────
 *  Space     : 再生 / 一時停止
 *  ←/→       : 1フレーム移動 (30fps想定)
 *  Shift+←/→ : 10秒スキップ
 *  Tab       : プレイヤー切替 (A ↔ B)
 *  Enter     : ラリー終了確認画面へ
 *  Ctrl+Z    : アンドゥ
 *  Escape    : キャンセル (rally_end → idle, land_zone → idle)
 */

// エンドタイプ: cant_reach はショット種別から削除、エンドタイプとしてのみ残す
const END_TYPE_KEYS = ['ace', 'forced_error', 'unforced_error', 'net', 'out', 'cant_reach']

// テンキー → 落点ゾーン（null = スキップ）
const NUMPAD_ZONE: Record<string, Zone9 | null> = {
  Numpad7: 'BL', Numpad8: 'BC', Numpad9: 'BR',
  Numpad4: 'ML', Numpad5: 'MC', Numpad6: 'MR',
  Numpad1: 'NL', Numpad2: 'NC', Numpad3: 'NR',
  Numpad0: null,          // スキップ
  NumpadDecimal: null,    // スキップ（.キー）
  NumpadEnter: null,      // スキップ（Enterキー）
}

export function useKeyboard({ videoRef, enabled = true, onEndTypeSelect }: UseKeyboardOptions = {}) {
  const store = useAnnotationStore()

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      const { inputStep, isRallyActive, currentStrokes } = store

      // K-001: マッチデーモード — rally_end 中に 1–6 でエンドタイプ選択
      // 通常の数字キーのみ（テンキーは落点入力に使用するため除外）
      if (
        inputStep === 'rally_end' &&
        onEndTypeSelect &&
        !e.ctrlKey && !e.metaKey && !e.altKey &&
        !e.code.startsWith('Numpad')
      ) {
        const idx = parseInt(e.key) - 1
        if (idx >= 0 && idx < END_TYPE_KEYS.length) {
          e.preventDefault()
          onEndTypeSelect(END_TYPE_KEYS[idx])
          return
        }
      }

      // ─── テンキー処理（落点入力・属性トグル） ───────────────────────────────
      if (e.code.startsWith('Numpad') && !e.ctrlKey && !e.metaKey && !e.altKey) {
        // 属性テンキー: ラリー中かつ落点待ちまたはidle時
        if (isRallyActive && (inputStep === 'land_zone' || inputStep === 'idle')) {
          if (e.code === 'NumpadDivide') {
            e.preventDefault()
            store.toggleAttribute('is_backhand')
            return
          }
          if (e.code === 'NumpadMultiply') {
            e.preventDefault()
            store.toggleAttribute('is_around_head')
            return
          }
          if (e.code === 'NumpadSubtract') {
            e.preventDefault()
            store.cycleAboveNet()
            return
          }
        }

        // 落点テンキー: 落点待ちステップのみ有効
        if (inputStep === 'land_zone') {
          if (e.code in NUMPAD_ZONE) {
            e.preventDefault()
            const zone = NUMPAD_ZONE[e.code]
            if (zone === null) {
              // スキップ（Numpad0, NumpadDecimal, NumpadEnter）
              store.skipLandZone()
            } else {
              store.selectLandZone(zone)
            }
            return
          }
        }
      }

      // ─── 動画シーク（常時有効） ──────────────────────────────────────────────
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

      // Space: 再生/一時停止
      if (e.key === ' ') {
        e.preventDefault()
        const v = videoRef?.current
        if (!v) return
        v.paused ? v.play() : v.pause()
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

      // Enter: ラリー終了確認へ（テンキーEnterは落点スキップで上で処理済み）
      if (e.key === 'Enter' && e.code !== 'NumpadEnter') {
        e.preventDefault()
        if (isRallyActive && currentStrokes.length > 0 && inputStep !== 'rally_end') {
          store.endRallyRequest()
        }
        return
      }

      // ショット種別キー: テンキー数字と区別するため e.code で判定
      // idle または land_zone ステップ時のみ有効
      if (
        (inputStep === 'idle' || inputStep === 'land_zone') &&
        !e.ctrlKey && !e.metaKey && !e.altKey &&
        !e.code.startsWith('Numpad')  // テンキーの数字は落点入力に使用
      ) {
        const key = e.key.toLowerCase()
        const shotType = KEYBOARD_MAP[key] as ShotType | undefined
        if (shotType) {
          e.preventDefault()
          const v = videoRef?.current
          if (v && !v.paused) v.pause()
          const currentSec = v?.currentTime ?? 0
          store.inputShotType(shotType, currentSec)
          return
        }
      }
    },
    [enabled, store, videoRef, onEndTypeSelect]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}
