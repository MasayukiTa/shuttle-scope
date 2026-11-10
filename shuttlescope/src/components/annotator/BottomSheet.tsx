/**
 * U7: モバイル用ボトムシート (右パネル代替)。
 *
 * 768px 未満で右パネルを bottom-sheet として表示する。
 *  - デフォルトは折り畳み (タップで展開)
 *  - 展開時 max-h は viewport の 70%
 *  - children に既存の右パネル内容を渡す
 *  - drag handle で上下スワイプ展開/折り畳み (タップ展開も可)
 */
import { PointerEvent as ReactPointerEvent, ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { MIcon } from '@/components/common/MIcon'

/** ドラッグで開閉を切り替えるための最小移動量(px) */
const DRAG_THRESHOLD_PX = 28

interface BottomSheetProps {
  /** 表示中ラベル (例 '入力 / 確認 / 解析 / 設定') */
  label?: string
  children: ReactNode
  /** 初期 open 状態 */
  defaultOpen?: boolean
  /** Sheet を完全に閉じる時のコールバック (× ボタン or Esc)。指定しなければ collapse のみ */
  onClose?: () => void
}

export function BottomSheet({ label, children, defaultOpen = false, onClose }: BottomSheetProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(defaultOpen)

  // ドラッグ追跡用 ref。開始 Y と、直後の click を無効化するか。
  const startYRef = useRef<number | null>(null)
  const suppressClickRef = useRef(false)

  const collapseOrClose = useCallback(() => {
    if (onClose) onClose()
    else setOpen(false)
  }, [onClose])

  // Esc で閉じる
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        collapseOrClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, collapseOrClose])

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLButtonElement>) => {
    // 主ボタン / タッチ / ペンのみ追跡
    if (e.button !== 0 && e.pointerType === 'mouse') return
    startYRef.current = e.clientY
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      // setPointerCapture 非対応環境でも click フォールバックが動く
    }
  }, [])

  const onPointerMove = useCallback((e: ReactPointerEvent<HTMLButtonElement>) => {
    const startY = startYRef.current
    if (startY === null) return
    const dy = e.clientY - startY
    if (Math.abs(dy) < DRAG_THRESHOLD_PX) return
    // 閾値を超えた: 方向で開閉を確定させ、直後の click は無効化
    suppressClickRef.current = true
    if (dy < 0) {
      setOpen(true)
    } else if (onClose) {
      onClose()
    } else {
      setOpen(false)
    }
    startYRef.current = null
  }, [onClose])

  const onPointerEnd = useCallback((e: ReactPointerEvent<HTMLButtonElement>) => {
    startYRef.current = null
    try {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId)
      }
    } catch {
      // noop
    }
  }, [])

  const onClick = useCallback(() => {
    // ドラッグで開閉した直後の合成 click は 1 回スキップ(二重発火防止)
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      return
    }
    setOpen((v) => !v)
  }, [])

  return (
    <div
      className={clsx(
        'fixed left-0 right-0 bottom-0 z-30 bg-[var(--ss-surface-1)] border-t border-[var(--ss-border)] shadow-pop transition-transform duration-base ease-out',
        open ? 'translate-y-0' : 'translate-y-[calc(100%-44px)]',
      )}
      style={{ maxHeight: '78vh' }}
      role="region"
      aria-label={t('annotator.ux.bottom_sheet_aria')}
    >
      <div className="flex items-center">
        <button
          type="button"
          onClick={onClick}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerEnd}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)] active:bg-[var(--ss-surface-3)]"
          style={{ touchAction: 'none' }}
          aria-expanded={open}
          aria-label={t('annotator.ux.bottom_sheet_handle')}
        >
          <span className="block w-10 h-1 rounded-ss-sm bg-[var(--ss-border-strong)]" />
          {label && <span className="ml-2">{label}</span>}
          <MIcon name={open ? 'expand_more' : 'expand_less'} size={16} />
        </button>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t('annotator.ux.bottom_sheet_close')}
            className="w-9 h-9 flex items-center justify-center text-[var(--ss-t3)] hover:text-[var(--ss-t1)] hover:bg-[var(--ss-surface-2)]"
          >
            <MIcon name="close" size={18} />
          </button>
        )}
      </div>
      {open && (
        <div className="overflow-y-auto" style={{ maxHeight: 'calc(78vh - 44px)' }}>
          {children}
        </div>
      )}
    </div>
  )
}
