import { useEffect, useCallback, useRef } from 'react'
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
  /** プレラリー中に 1/2 キー（テンキー含む）でサーバーを選択 */
  onServerSelect?: (player: 'player_a' | 'player_b') => void
  /** ダブルスモードで Tab キーによりチーム内ヒッターを切替 */
  onToggleHitter?: () => void
  /** ダブルスモードで 7/8/9/0 キーにより直接打者を選択 */
  onHitterSelect?: (hitter: 'player_a' | 'partner_a' | 'partner_b' | 'player_b') => void
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
 *   1 / Numpad1 : player_a をサーバーに選択
 *   2 / Numpad2 : player_b をサーバーに選択
 *
 * 【idle(true) = ショット選択中】
 *   ショットキー (N/C/P/S/D/V/L/O/X/Z/F/H/B/G, 1/2=サービス) : ショット入力
 *   7/8/9/0     : ダブルス打者選択 (player_a/partner_a/partner_b/player_b)
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
 *   ── 着地点 (Numpad / 文字キー) ──
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
 *   ── 打点 override (トップ行 1-9) ──
 *   1-9 (トップ行 Digit1〜Digit9) : 打点 1-9 を override (HitZoneSelector と同じ 3x3 配置)
 *   ── キャンセル ──
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

// トップ行 1-9 → hit_zone (打点) override
// HitZoneSelector の 3x3 配置 (上段=左奥/中奥/右奥, 中段=左中/中中/右中, 下段=左前/中前/右前) に対応
// e.code === 'Digit1'..'Digit9' のときのみ反応 (Numpad は land_zone 用に温存)
const DIGIT_HIT_ZONE: Record<string, number> = {
  Digit1: 1, Digit2: 2, Digit3: 3,
  Digit4: 4, Digit5: 5, Digit6: 6,
  Digit7: 7, Digit8: 8, Digit9: 9,
}

/** フォーカスが入力系要素内にあるか確認 */
function isInInputContext(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false
  const tag = (target as HTMLElement).tagName
  // BUTTON は除外 — Space でボタンがクリックされる問題を防ぐため、
  // ハンドラ側で e.preventDefault() + blur() を行う
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return true
  if ((target as HTMLElement).isContentEditable) return true
  // カスタムコンボボックス / リストボックス内
  if ((target as HTMLElement).closest('[role="combobox"],[role="listbox"],[role="option"]')) return true
  return false
}

const HITTER_KEYS: Record<string, 'player_a' | 'partner_a' | 'partner_b' | 'player_b'> = {
  '7': 'player_a', '8': 'partner_a', '9': 'partner_b', '0': 'player_b',
}

// テンキーでもサーバー/ヒッター選択（idle step のみ。land_zone での落点入力と競合しない）
const NUMPAD_HITTER_KEYS: Record<string, 'player_a' | 'partner_a' | 'partner_b' | 'player_b'> = {
  'Numpad7': 'player_a', 'Numpad8': 'partner_a', 'Numpad9': 'partner_b', 'Numpad0': 'player_b',
}

export function useKeyboard({
  videoRef,
  enabled = true,
  onEndTypeSelect,
  onWinnerSelect,
  onSkipRallyOpen,
  onServerSelect,
  onToggleHitter,
  onHitterSelect,
}: UseKeyboardOptions = {}) {
  // Use refs for callbacks so handleKeyDown never needs to be recreated when they change
  const onEndTypeSelectRef = useRef(onEndTypeSelect)
  const onWinnerSelectRef = useRef(onWinnerSelect)
  const onSkipRallyOpenRef = useRef(onSkipRallyOpen)
  const onServerSelectRef = useRef(onServerSelect)
  const onToggleHitterRef = useRef(onToggleHitter)
  const onHitterSelectRef = useRef(onHitterSelect)
  onEndTypeSelectRef.current = onEndTypeSelect
  onWinnerSelectRef.current = onWinnerSelect
  onSkipRallyOpenRef.current = onSkipRallyOpen
  onServerSelectRef.current = onServerSelect
  onToggleHitterRef.current = onToggleHitter
  onHitterSelectRef.current = onHitterSelect

  const enabledRef = useRef(enabled)
  enabledRef.current = enabled

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabledRef.current) return
      if (isInInputContext(e.target)) return

      // Access store state directly to avoid stale closure issues
      const store = useAnnotationStore.getState()
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
          // フォーカスがボタンにある場合、Space でそのボタンがクリックされないよう blur する
          const active = document.activeElement
          if (active instanceof HTMLElement && active.tagName === 'BUTTON') {
            active.blur()
          }
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
            onEndTypeSelectRef.current?.(END_TYPE_KEYS[idx])
            return
          }
        }
        // A/B: 勝者確定
        if (!e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
          if (e.key === 'a' || e.key === 'A') {
            e.preventDefault()
            onWinnerSelectRef.current?.('player_a')
            return
          }
          if (e.key === 'b' || e.key === 'B') {
            e.preventDefault()
            onWinnerSelectRef.current?.('player_b')
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

        // Shift+1..9 (ダブルス用 hit_zone エスケープ): doubles で 7/8/9 が hitter に
        // 奪われたとき、hit_zone を入力したいユーザのための逃げ道。
        // singles では Shift 不要 (Digit1..Digit9 が直接 hit_zone)。
        if (e.shiftKey && store.isDoubles && e.code in DIGIT_HIT_ZONE) {
          e.preventDefault()
          store.setHitZoneOverride(DIGIT_HIT_ZONE[e.code] as unknown as Zone9)
          return
        }

        // ダブルス: 7/8/9/0 (トップ行) を hitter 選択にリダイレクト (Shift なしのみ)
        // 1-6 はそのまま hit_zone (singles と同じ挙動)
        if (store.isDoubles && !e.shiftKey) {
          if (e.code === 'Digit7') { e.preventDefault(); onHitterSelectRef.current?.('player_a'); return }
          if (e.code === 'Digit8') { e.preventDefault(); onHitterSelectRef.current?.('partner_a'); return }
          if (e.code === 'Digit9') { e.preventDefault(); onHitterSelectRef.current?.('partner_b'); return }
          if (e.code === 'Digit0') { e.preventDefault(); onHitterSelectRef.current?.('player_b'); return }
        }

        // トップ行 1-9 → hit_zone (打点) override (Digit1..Digit9)
        // Numpad は land_zone 用なので干渉しない
        if (e.code in DIGIT_HIT_ZONE) {
          e.preventDefault()
          // pendingStroke.hit_zone は Zone9 string 型だが既存実装で number もサポート
          // (HitZoneSelector が `[1..9]` で setHitZoneOverride を呼ぶため)
          store.setHitZoneOverride(DIGIT_HIT_ZONE[e.code] as unknown as Zone9)
          return
        }

        // 0: スキップ（数字キー、シングルスのみ。ダブルスは player_b hitter が優先される）
        if (e.key === '0' && !e.code.startsWith('Numpad') && !store.isDoubles) {
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
          onSkipRallyOpenRef.current?.()
          return
        }
        // 1 / Numpad1: player_a をサーバーに選択
        if ((e.key === '1' && !e.code.startsWith('Numpad')) || e.code === 'Numpad1') {
          e.preventDefault()
          onServerSelectRef.current?.('player_a')
          return
        }
        // 2 / Numpad2: player_b をサーバーに選択
        if ((e.key === '2' && !e.code.startsWith('Numpad')) || e.code === 'Numpad2') {
          e.preventDefault()
          onServerSelectRef.current?.('player_b')
          return
        }
        // プレラリー中はその他のショット/ランディングキーを無効化
        return
      }

      // ─── idle(true): ラリー中・ショット選択 ────────────────────────────────

      // Ctrl+Z: 直前ストロークをアンドゥ（削除ストロークのタイムスタンプへシーク）
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault()
        const removed = store.undoLastStroke()
        if (removed?.timestamp_sec != null && videoRef?.current) {
          videoRef.current.currentTime = removed.timestamp_sec
        }
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

      // Tab: ダブルスモードのみ — チーム内ヒッター切替
      if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault()
        onToggleHitterRef.current?.()
        return
      }

      // 7/8/9/0: ダブルス打者直接選択（通常数字キー）
      if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !e.code.startsWith('Numpad')) {
        const hitter = HITTER_KEYS[e.key]
        if (hitter) {
          e.preventDefault()
          onHitterSelectRef.current?.(hitter)
          return
        }
      }

      // Numpad7/8/9/0: テンキーでもサーバー/打者選択（idle step のみ。land_zone の落点入力と競合しない）
      if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const hitter = NUMPAD_HITTER_KEYS[e.code]
        if (hitter) {
          e.preventDefault()
          onHitterSelectRef.current?.(hitter)
          return
        }
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
    // videoRef is a stable ref object. All other deps (enabled, callbacks) are accessed via refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [videoRef]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}
