import { useEffect, useCallback } from 'react'
import { useAnnotationStore } from '@/store/annotationStore'
import { KEYBOARD_MAP, getValidShotTypes } from '@/components/annotation/ShotTypePanel'
import { ShotType, Zone9, ZoneOOB, ZoneNet } from '@/types'

interface UseKeyboardOptions {
  videoRef?: React.RefObject<HTMLVideoElement>
  enabled?: boolean
  /** rally_end 中に 1–6 キーでエンドタイプ選択 */
  onEndTypeSelect?: (endType: string) => void
  /** rally_end 中に A/B キーで勝者確定 */
  onWinnerSelect?: (winner: 'player_a' | 'player_b') => void
  /** プレラリー中に K キーで見逃しラリーダイアログを開く */
  onSkipRallyOpen?: () => void
}

/**
 * キーボードショートカット一元管理フック
 *
 * ─── ステップ別有効キー ────────────────────────────────────────────────────────
 *
 * 【グローバル（常時、テキスト入力フォーカス外のみ）】
 *   Space     : 再生 / 一時停止
 *   ←/→       : 1フレーム移動 (30fps)
 *   Shift+←/→ : 10秒スキップ
 *
 * 【idle(false) = プレラリー】
 *   Enter : ラリー開始
 *   K     : 見逃しラリーダイアログを開く
 *
 * 【idle(true) = ショット選択中】
 *   ショットキー (N/C/P/S/D/V/L/O/X/Z/F/H/B/G, 1/2=サービス) : ショット入力
 *   Q           : バックハンドトグル
 *   W           : ラウンドヘッドトグル
 *   E           : ネット上下サイクル
 *   NumpadDivide   : バックハンドトグル（サブ）
 *   NumpadMultiply : ラウンドヘッドトグル（サブ）
 *   NumpadSubtract : ネット上下サイクル（サブ）
 *   Enter       : ラリー終了確認へ（確定済みストロークが1本以上ある場合）
 *   Ctrl+Z      : 直前ストロークをアンドゥ
 *
 * 【land_zone = 落点選択中】
 *   U/I/O       : BL/BC/BR（バックゾーン）
 *   J/K/L       : ML/MC/MR（ミドルゾーン）
 *   M/,/.       : NL/NC/NR（ネットゾーン）
 *   Numpad7-9   : BL/BC/BR
 *   Numpad4-6   : ML/MC/MR
 *   Numpad1-3   : NL/NC/NR
 *   Shift+U/I/O : OB_BL/OB_BC/OB_BR（バックライン外）
 *   Shift+J     : OB_LM（左サイド外ミド）
 *   Shift+L     : OB_RM（右サイド外ミド）
 *   Shift+M     : OB_FL（ネット前左外）
 *   Shift+.     : OB_FR（ネット前右外）
 *   - / = / \   : NET_L / NET_C / NET_R
 *   0 / Numpad0 / NumpadDecimal : 落点スキップ
 *   Escape / Backspace          : ペンディングストローク キャンセル
 *   Ctrl+Z                      : ペンディングストローク キャンセル（確定済みは消さない）
 *
 * 【rally_end = ラリー終了確認中】
 *   1–6     : エンドタイプ選択 (onEndTypeSelect コールバック)
 *   A       : Player A 勝者確定 (onWinnerSelect)
 *   B       : Player B 勝者確定 (onWinnerSelect)
 *   Escape  : ラリー終了キャンセル → idle に戻る
 *
 * ─── フォーカスガード ───────────────────────────────────────────────────────────
 *   INPUT / TEXTAREA / SELECT / BUTTON / [contenteditable] 内ではすべて無効。
 */

const END_TYPE_KEYS = ['ace', 'forced_error', 'unforced_error', 'net', 'out', 'cant_reach']

// テンキー → 落点ゾーン（null = スキップ）
const NUMPAD_ZONE: Record<string, Zone9 | null> = {
  Numpad7: 'BL', Numpad8: 'BC', Numpad9: 'BR',
  Numpad4: 'ML', Numpad5: 'MC', Numpad6: 'MR',
  Numpad1: 'NL', Numpad2: 'NC', Numpad3: 'NR',
  Numpad0: null,
  NumpadDecimal: null,
}

// 文字キー → 落点ゾーン（land_zone ステップのみ）
const LETTER_ZONE: Record<string, Zone9> = {
  'u': 'BL', 'i': 'BC', 'o': 'BR',
  'j': 'ML', 'k': 'MC', 'l': 'MR',
  'm': 'NL', ',': 'NC', '.': 'NR',
}

// Shift+文字キー → OOBゾーン（land_zone ステップのみ）
const SHIFT_OOB: Record<string, ZoneOOB> = {
  'U': 'OB_BL', 'I': 'OB_BC', 'O': 'OB_BR',
  'J': 'OB_LM', 'L': 'OB_RM',
  'M': 'OB_FL', '>': 'OB_FR',  // Shift+. = >
}

// 文字キー → NETゾーン（land_zone ステップのみ）
const NET_KEY: Record<string, ZoneNet> = {
  '-': 'NET_L', '=': 'NET_C', '\\': 'NET_R',
}

/** フォーカスが入力系要素内にあるか確認 */
function isInInputContext(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false
  const tag = (target as HTMLElement).tagName
  if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tag)) return true
  if ((target as HTMLElement).isContentEditable) return true
  // カスタムコンボボックス / リストボックス内
  if ((target as HTMLElement).closest('[role="combobox"],[role="listbox"],[role="option"]')) return true
  return false
}

export function useKeyboard({
  videoRef,
  enabled = true,
  onEndTypeSelect,
  onWinnerSelect,
  onSkipRallyOpen,
}: UseKeyboardOptions = {}) {
  const store = useAnnotationStore()

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled) return
      if (isInInputContext(e.target)) return

      const { inputStep, isRallyActive, currentStrokes, currentStrokeNum, pendingStroke } = store

      // ─── グローバル: 動画シーク（常時有効） ────────────────────────────────
      if (!e.ctrlKey && !e.metaKey && !e.altKey) {
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
        if (!e.shiftKey && e.key === 'ArrowLeft') {
          e.preventDefault()
          if (videoRef?.current)
            videoRef.current.currentTime = Math.max(0, videoRef.current.currentTime - 1 / 30)
          return
        }
        if (!e.shiftKey && e.key === 'ArrowRight') {
          e.preventDefault()
          if (videoRef?.current)
            videoRef.current.currentTime = Math.min(
              videoRef.current.duration ?? 0,
              videoRef.current.currentTime + 1 / 30
            )
          return
        }
        if (e.key === ' ') {
          e.preventDefault()
          const v = videoRef?.current
          if (v) v.paused ? v.play() : v.pause()
          return
        }
      }

      // ═══════════════════════════════════════════════════════════════════════
      // ステップ別処理
      // ═══════════════════════════════════════════════════════════════════════

      // ─── rally_end ─────────────────────────────────────────────────────────
      if (inputStep === 'rally_end') {
        // Escape: キャンセル → idle
        if (e.key === 'Escape') {
          e.preventDefault()
          store.cancelRallyEnd()
          return
        }
        // 1–6: エンドタイプ選択
        if (!e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && !e.code.startsWith('Numpad')) {
          const idx = parseInt(e.key) - 1
          if (idx >= 0 && idx < END_TYPE_KEYS.length) {
            e.preventDefault()
            onEndTypeSelect?.(END_TYPE_KEYS[idx])
            return
          }
        }
        // A/B: 勝者確定
        if (!e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
          if (e.key === 'a' || e.key === 'A') {
            e.preventDefault()
            onWinnerSelect?.('player_a')
            return
          }
          if (e.key === 'b' || e.key === 'B') {
            e.preventDefault()
            onWinnerSelect?.('player_b')
            return
          }
        }
        // rally_end 中はその他のキーをすべて無効化
        return
      }

      // ─── land_zone ─────────────────────────────────────────────────────────
      if (inputStep === 'land_zone') {
        // Escape / Backspace: ペンディングをキャンセル
        if (e.key === 'Escape' || e.key === 'Backspace') {
          e.preventDefault()
          store.cancelPendingStroke()
          return
        }
        // Ctrl+Z: ペンディングをキャンセル（確定済みストロークは消さない）
        if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
          e.preventDefault()
          store.cancelPendingStroke()
          return
        }
        if (e.ctrlKey || e.metaKey || e.altKey) return

        // 属性テンキー（land_zone 中も変更可能）
        if (e.code === 'NumpadDivide') { e.preventDefault(); store.toggleAttribute('is_backhand'); return }
        if (e.code === 'NumpadMultiply') { e.preventDefault(); store.toggleAttribute('is_around_head'); return }
        if (e.code === 'NumpadSubtract') { e.preventDefault(); store.cycleAboveNet(); return }

        // テンキー落点（Numpad1-9 / Numpad0 / NumpadDecimal）
        if (e.code in NUMPAD_ZONE) {
          e.preventDefault()
          const zone = NUMPAD_ZONE[e.code]
          if (zone === null) {
            store.skipLandZone()
          } else {
            store.selectLandZone(zone)
          }
          return
        }

        // 0: スキップ（数字キー）
        if (e.key === '0' && !e.code.startsWith('Numpad')) {
          e.preventDefault()
          store.skipLandZone()
          return
        }

        // Shift+文字キー: OOBゾーン
        if (e.shiftKey) {
          const oob = SHIFT_OOB[e.key]
          if (oob) {
            e.preventDefault()
            store.selectLandZone(oob)
            return
          }
          return
        }

        // NETゾーン（- / = / \）
        const netZone = NET_KEY[e.key]
        if (netZone) {
          e.preventDefault()
          store.selectLandZone(netZone)
          return
        }

        // 文字キー落点（U/I/O J/K/L M/,/.）
        const letterZone = LETTER_ZONE[e.key.toLowerCase()]
        if (letterZone) {
          e.preventDefault()
          store.selectLandZone(letterZone)
          return
        }

        // land_zone 中はその他のキーをすべて無効化（Enter を含む）
        return
      }

      // ─── idle ──────────────────────────────────────────────────────────────
      // （isRallyActive=false = プレラリー、isRallyActive=true = ショット選択中）

      if (!isRallyActive) {
        // プレラリー: Enter でラリー開始、K で見逃しラリー
        if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
          e.preventDefault()
          store.startRally(videoRef?.current?.currentTime ?? 0)
          return
        }
        if ((e.key === 'k' || e.key === 'K') && !e.ctrlKey && !e.metaKey) {
          e.preventDefault()
          onSkipRallyOpen?.()
          return
        }
        // プレラリー中はその他のショット/ランディングキーを無効化
        return
      }

      // ─── idle(true): ラリー中・ショット選択 ────────────────────────────────

      // Ctrl+Z: 直前ストロークをアンドゥ
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault()
        store.undoLastStroke()
        return
      }

      if (e.ctrlKey || e.metaKey || e.altKey) return

      // Enter: ラリー終了確認へ（確定済みストロークが1本以上ある場合）
      if (e.key === 'Enter' && !e.shiftKey && e.code !== 'NumpadEnter') {
        e.preventDefault()
        if (currentStrokes.length > 0) {
          store.endRallyRequest()
        }
        return
      }

      // 属性キー（Q/W/E + Numpad）
      if (!e.shiftKey) {
        if (e.key === 'q' || e.key === 'Q') { e.preventDefault(); store.toggleAttribute('is_backhand'); return }
        if (e.key === 'w' || e.key === 'W') { e.preventDefault(); store.toggleAttribute('is_around_head'); return }
        if (e.key === 'e' || e.key === 'E') { e.preventDefault(); store.cycleAboveNet(); return }
      }
      if (e.code === 'NumpadDivide') { e.preventDefault(); store.toggleAttribute('is_backhand'); return }
      if (e.code === 'NumpadMultiply') { e.preventDefault(); store.toggleAttribute('is_around_head'); return }
      if (e.code === 'NumpadSubtract') { e.preventDefault(); store.cycleAboveNet(); return }

      // ショットキー（テンキーは除外）
      if (!e.shiftKey && !e.code.startsWith('Numpad')) {
        const key = e.key.toLowerCase()
        const shotType = KEYBOARD_MAP[key] as ShotType | undefined
        if (shotType) {
          // コンテキストに応じた有効ショット種別でフィルタ
          const lastShotType = currentStrokes.length > 0
            ? currentStrokes[currentStrokes.length - 1].shot_type
            : null
          const validShots = getValidShotTypes(currentStrokeNum, lastShotType)
          if (!validShots.has(shotType)) return  // このコンテキストでは非表示 → 無効

          e.preventDefault()
          const v = videoRef?.current
          if (v && !v.paused) v.pause()
          store.inputShotType(shotType, v?.currentTime ?? 0)
          return
        }
      }
    },
    [enabled, store, videoRef, onEndTypeSelect, onWinnerSelect, onSkipRallyOpen]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}
