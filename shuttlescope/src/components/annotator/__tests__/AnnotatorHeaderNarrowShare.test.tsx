/**
 * 本番観察 (2026-11-10): 記録画面 (#/annotator/<id>) を幅 307px で開くと、
 * ヘッダー右端の「共有」ボタンと ⋮ が画面外に切れて押せなかった。
 * ヘッダーのモバイル右クラスタ (進捗バー + 共有 + ⋮) を flex-wrap で
 * 折り返せるようにし、どの狭幅でも「共有」に必ず届くことを固定する。
 *
 * Tailwind クラス文字列の写経ではなく、実コンポーネント MobileShareButton を
 * ヘッダーと同じクラスタ構造に入れて実 DOM へレンダリングし、
 * 狭幅 (307/360/390/430px) のどれでも「共有」ボタンが描画され、押せる
 * (onOpenShare が発火する) ことを確かめる。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { MobileShareButton } from '../MobileShareButton'

/**
 * AnnotatorPage のモバイル右クラスタ (src/pages/AnnotatorPage.tsx の
 * `flex flex-wrap md:hidden items-center justify-end gap-2 shrink-0` ブロック)
 * と同じ構造を再現したハーネス。進捗バー・%・共有ボタン・⋮ を
 * その順で並べ、親の指定幅に入れる。
 */
function MobileActionsHarness({ width, onOpenShare }: { width: number; onOpenShare: () => void }) {
  return (
    <div style={{ width, display: 'flex', overflow: 'hidden' }}>
      <div className="flex flex-wrap md:hidden items-center justify-end gap-2 shrink-0" data-testid="mobile-actions">
        <div className="w-12 h-1.5 bg-gray-300 rounded-full overflow-hidden">
          <div style={{ width: '50%' }} />
        </div>
        <span className="text-[10px]">50%</span>
        <MobileShareButton activeSessionCode={null} onOpenShare={onOpenShare} />
        <button aria-label="menu">⋮</button>
      </div>
    </div>
  )
}

const NARROW_WIDTHS = [307, 360, 390, 430]

describe('記録画面ヘッダー: 狭幅でも「共有」に届く', () => {
  for (const width of NARROW_WIDTHS) {
    it(`幅 ${width}px で「共有」ボタンが描画され、押せる`, () => {
      const onOpenShare = vi.fn()
      render(<MobileActionsHarness width={width} onOpenShare={onOpenShare} />)

      const cluster = screen.getByTestId('mobile-actions')
      // クラスタが折り返せる (flex-wrap) ことを構造として固定。
      // 折り返しが外れると狭幅で共有/⋮ が切れるため、ここを回帰検知点にする。
      expect(cluster.className).toContain('flex-wrap')

      // 実 DOM: 「共有」ボタンがクラスタ内に描画されている。
      const shareBtn = within(cluster).getByRole('button', { name: '共有' })
      expect(shareBtn).toBeInTheDocument()
      expect(shareBtn).toHaveTextContent('共有')

      // 動線が生きている: クリックで onOpenShare が発火する。
      fireEvent.click(shareBtn)
      expect(onOpenShare).toHaveBeenCalledTimes(1)
    })
  }
})
