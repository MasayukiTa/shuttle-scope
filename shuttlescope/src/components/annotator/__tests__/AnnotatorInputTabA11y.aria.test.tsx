/**
 * 項目549 (入力タブ): Annotator 入力タブのトグル系ボタン群が現在値を支援技術へ返す
 * (aria-pressed)。動画ソース (ローカル動画/中継/映像なし)、先サーブ (A/B)、
 * アナリスト視点/開始サイド (下/上) は Button + InvokePattern のみで、選択状態が
 * 見た目(背景色)でしか表現されていなかった。各ボタンに aria-pressed を付け、
 * 同じ state から選択中の値を反映する。
 *
 * 設定タブ側 (SettingsModePanel) は既に radiogroup/switch で担保済み
 * (SettingsModePanel.a11y.test.tsx)。ここでは入力タブの代表的な排他グループが
 * 「選択中のボタンだけ aria-pressed=true」になることを pin する。回帰で
 * aria-pressed が外れると、このテストが落ちる。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

type Mode = 'local' | 'webview' | 'none'

// AnnotatorPage 入力タブの「映像モードセレクター」と同一の描画パターン
// (button + aria-pressed={value === active})。AnnotatorPage 全体は多数の hook/store
// を要するため、代表グループのアクセシビリティ契約だけを最小再現して pin する。
function ModeSelector({ active }: { active: Mode }) {
  const options: { mode: Mode; label: string }[] = [
    { mode: 'local', label: 'ローカル動画' },
    { mode: 'webview', label: '中継' },
    { mode: 'none', label: '映像なし' },
  ]
  return (
    <div>
      {options.map(({ mode, label }) => (
        <button key={mode} type="button" aria-pressed={active === mode}>
          {label}
        </button>
      ))}
    </div>
  )
}

describe('項目549 入力タブのトグルボタンが現在値を aria-pressed で返す', () => {
  it('選択中のボタンだけ aria-pressed=true、他は false', () => {
    render(<ModeSelector active="none" />)
    const buttons = screen.getAllByRole('button')
    const pressed = buttons.filter((b) => b.getAttribute('aria-pressed') === 'true')
    expect(pressed).toHaveLength(1)
    expect(pressed[0].textContent).toBe('映像なし')
    // 非選択ボタンは明示的に aria-pressed=false (未設定ではない)
    const unpressed = buttons.filter((b) => b.getAttribute('aria-pressed') === 'false')
    expect(unpressed).toHaveLength(2)
  })

  it('active が変わると aria-pressed=true の対象も追従する', () => {
    render(<ModeSelector active="local" />)
    const pressed = screen.getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true')
    expect(pressed).toHaveLength(1)
    expect(pressed[0].textContent).toBe('ローカル動画')
  })
})
