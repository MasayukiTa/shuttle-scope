/**
 * 触覚フィードバック hook (Phase C speed slice).
 *
 * モバイル/タブレットで「タップが入った」確信を体感させる。
 * navigator.vibrate 非対応環境 (iOS Safari, Electron 等) では noop で
 * graceful degradation する。
 *
 * 使用例:
 *   const haptic = useHapticFeedback()
 *   <button onClick={() => { haptic.shotTap(); doStuff() }}>
 */
import { useCallback, useMemo } from 'react'

type Pattern = number | number[]

function safeVibrate(pattern: Pattern): void {
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      navigator.vibrate(pattern)
    }
  } catch {
    // Some platforms throw on unsupported patterns; swallow silently.
  }
}

export interface HapticFeedback {
  /** 軽いタップ (打者選択, ショット種別 etc) */
  tap: () => void
  /** ストローク確定 (二段ブレ) */
  strokeConfirm: () => void
  /** Undo / 取消 */
  undo: () => void
  /** モード切替 (RALLY → RESULT 等) */
  modeSwitch: () => void
  /** エラー (API 失敗, 不可能操作) */
  error: () => void
}

export function useHapticFeedback(): HapticFeedback {
  const tap = useCallback(() => safeVibrate(20), [])
  const strokeConfirm = useCallback(() => safeVibrate([10, 30, 10]), [])
  const undo = useCallback(() => safeVibrate(60), [])
  const modeSwitch = useCallback(() => safeVibrate([15, 50, 15]), [])
  const error = useCallback(() => safeVibrate(200), [])

  return useMemo(
    () => ({ tap, strokeConfirm, undo, modeSwitch, error }),
    [tap, strokeConfirm, undo, modeSwitch, error],
  )
}
