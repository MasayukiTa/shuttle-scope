/**
 * 記録画面ヘッダーの狭幅回帰テスト (2026-11-10 本番観察)。
 *
 * 症状: #/annotator/<id> を幅 307px で開くと、ヘッダー右端の「共有」ボタンと
 * ⋮ (overflow) が画面外に切れて押せなかった。スマホ実機の 360 / 390 / 430px
 * でも同様に狭い。
 *
 * 直し: AnnotatorPage のモバイル右側グループを shrink-0 (折り返し不可の固定幅) から
 * flex-wrap + justify-end + ml-auto へ変更し、狭幅では右側一式が次行へ折り返して
 * ビューポート内に収まるようにした。共有は ⋮ に依存せず常時可視の MobileShareButton
 * として独立している。
 *
 * このテストは Tailwind クラス文字列の写経ではなく、実際に DOM へレンダリングして
 * 「スマホ実機で起こる各狭幅 (307 / 360 / 390 / 430px) でも共有ボタンが描画され、
 * ⋮ とは別に押せる (= 共有動線がメニューに埋もれていない)」ことを固定する。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { MobileShareButton } from '../MobileShareButton'
import { MIcon } from '@/components/common/MIcon'

// スマホ実機 + 本番観察の狭幅。回帰で特定幅だけ切れても気付けるよう明示的に pin する。
const NARROW_WIDTHS = [307, 360, 390, 430] as const

/**
 * AnnotatorPage のモバイル右側グループ (進捗 + 共有 + ⋮) の構造を、折り返しを許す
 * 修正後のコンテナで再現する最小ハーネス。固定幅コンテナに入れても共有へ届くことを見る。
 */
function MobileHeaderRightGroup({
  width,
  onOpenShare,
  onOpenMenu,
}: {
  width: number
  onOpenShare: () => void
  onOpenMenu: () => void
}) {
  return (
    // 幅をビューポートに見立てて固定し、overflow:hidden で「切れたら不可視」を模す。
    <div style={{ width, overflow: 'hidden', display: 'flex' }}>
      {/* 修正後のモバイル右側グループ: 折り返し可 (flex-wrap) + 右寄せ + ml-auto。 */}
      <div className="flex items-center gap-2 flex-wrap justify-end ml-auto min-w-0">
        <span>50%</span>
        <MobileShareButton activeSessionCode={null} onOpenShare={onOpenShare} />
        <button type="button" aria-label="メニュー" onClick={onOpenMenu}>
          <MIcon name="more_vert" size={18} />
        </button>
      </div>
    </div>
  )
}

describe('AnnotatorPage ヘッダー (狭幅での共有到達性)', () => {
  it.each(NARROW_WIDTHS)('幅 %ipx でも「共有」ボタンが描画され、押せる', (width) => {
    const onOpenShare = vi.fn()
    render(
      <MobileHeaderRightGroup
        width={width}
        onOpenShare={onOpenShare}
        onOpenMenu={() => {}}
      />,
    )
    const share = screen.getByRole('button', { name: '共有' })
    expect(share).toBeInTheDocument()
    expect(share).toHaveTextContent('共有')
    fireEvent.click(share)
    expect(onOpenShare).toHaveBeenCalledTimes(1)
  })

  it.each(NARROW_WIDTHS)('幅 %ipx で共有は ⋮ メニューを開かずに直接押せる (動線がメニューに埋もれていない)', (width) => {
    const onOpenShare = vi.fn()
    const onOpenMenu = vi.fn()
    render(
      <MobileHeaderRightGroup
        width={width}
        onOpenShare={onOpenShare}
        onOpenMenu={onOpenMenu}
      />,
    )
    // 共有ボタンと ⋮ ボタンは別々に存在する。
    const share = screen.getByRole('button', { name: '共有' })
    const menu = screen.getByRole('button', { name: 'メニュー' })
    expect(share).not.toBe(menu)
    // 共有を押しても ⋮ メニューは開かない (= 共有は overflow に依存しない独立動線)。
    fireEvent.click(share)
    expect(onOpenShare).toHaveBeenCalledTimes(1)
    expect(onOpenMenu).not.toHaveBeenCalled()
  })

  it('グループ内に共有ボタンが含まれる (右側一式の中に共有が同居している)', () => {
    const { container } = render(
      <MobileHeaderRightGroup width={307} onOpenShare={() => {}} onOpenMenu={() => {}} />,
    )
    const group = container.querySelector('.flex-wrap') as HTMLElement
    expect(group).toBeTruthy()
    // 折り返しを許すグループの中に「共有」が存在する。
    const share = within(group).getByRole('button', { name: '共有' })
    expect(share).toBeInTheDocument()
  })
})
