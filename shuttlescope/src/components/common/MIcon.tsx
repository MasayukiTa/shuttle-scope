/**
 * Material Symbols (Google Fonts) ラッパー。
 *
 * 方針 (2026-05-04 ユーザ要望):
 *   新規 UI のアイコンは Google Material Symbols (Outlined) で統一。
 *   絵文字 (🎯⚙ 等) と装飾 emoji-like icon の利用は禁止。
 *   既存の lucide-react は段階的に置換 (cosmetic refactor)。
 *
 * 使い方:
 *   <MIcon name="edit_note" size={18} />
 *
 * 利用可能な name は https://fonts.google.com/icons から検索。
 * 実体は npm package material-symbols のローカルフォント (CSP / 外部通信不要)。
 */
import { CSSProperties } from 'react'
import { clsx } from 'clsx'

interface MIconProps {
  /** Material Symbols icon name (e.g. 'edit_note', 'visibility', 'analytics', 'settings'). */
  name: string
  /** ピクセル単位サイズ。font-size に反映。デフォルト 20。 */
  size?: number
  /** Outlined fill (0=outline, 1=filled). デフォルト 0。 */
  fill?: 0 | 1
  /** ウェイト (100..700)。デフォルト 400。 */
  weight?: number
  /** 軸グレード (-25..200)。デフォルト 0。 */
  grade?: number
  /** 光学サイズ (20..48)。デフォルト 24。 */
  opticalSize?: number
  className?: string
  style?: CSSProperties
  ariaLabel?: string
  ariaHidden?: boolean
}

export function MIcon({
  name,
  size = 20,
  fill = 0,
  weight = 400,
  grade = 0,
  opticalSize = 24,
  className,
  style,
  ariaLabel,
  ariaHidden = true,
}: MIconProps) {
  return (
    <span
      className={clsx('material-symbols-outlined select-none', className)}
      aria-label={ariaLabel}
      aria-hidden={ariaHidden && !ariaLabel ? 'true' : undefined}
      role={ariaLabel ? 'img' : undefined}
      style={{
        fontSize: size,
        lineHeight: 1,
        fontVariationSettings: `'FILL' ${fill}, 'wght' ${weight}, 'GRAD' ${grade}, 'opsz' ${opticalSize}`,
        ...style,
      }}
    >
      {name}
    </span>
  )
}
