/**
 * アイコンだけのボタン。
 *
 * MIcon は既定で aria-hidden="true" を付けるため、button の中に MIcon だけを置くと
 * 支援技術上のボタン名が空になる。アイコン専用ボタンはこの部品を使い、
 * `label` (必須) をアクセシブル名として渡す。既存の素の button を直す場合は
 * `aria-label={t('...')}` を付ける。`__tests__/iconButtonNames.test.ts` が
 * アイコンだけで名前の無い button を CI で止める。
 */
import { forwardRef } from 'react'
import type { ButtonHTMLAttributes } from 'react'
import { MIcon } from '@/components/common/MIcon'

export interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'aria-label' | 'aria-labelledby'> {
  /** Material Symbols のアイコン名 */
  icon: string
  /** アクセシブル名 (必須)。画面に出ないので、操作の内容を表す文言を t() で渡す */
  label: string
  /** アイコンのピクセルサイズ。既定 16 */
  iconSize?: number
  /** アイコン側へ渡す className (回転・色など) */
  iconClassName?: string
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, iconSize = 16, iconClassName, type = 'button', title, ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} aria-label={label} title={title ?? label} {...rest}>
      <MIcon name={icon} size={iconSize} className={iconClassName} />
    </button>
  )
})
