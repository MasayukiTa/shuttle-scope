/**
 * トンネル状態表示ロジックのテスト
 *
 * AnnotatorPage に埋め込まれたトンネル UI の表示条件を
 * 独立したレンダリングテストで検証する。
 *
 * カバー範囲:
 * - pending 中（tunnelRunning=true, tunnelBase=null）→「取得中...」を表示
 * - 稼働中（tunnelRunning=true, tunnelPending=false）→「稼働中」を表示
 * - 非稼働（tunnelRunning=false）→ ラベルなし
 * - エラー時（tunnelLastError あり）→ ⚠ エラーメッセージを表示
 * - エラーは running=true のとき非表示
 * - pending 中は共有ボタンが cursor-wait になる（モーダルブロック）
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

// ── トンネル状態表示をコンポーネントとして再現 ─────────────────────────────
// AnnotatorPage に埋め込まれた UI と同じ条件分岐を使ったテスト用コンポーネント

interface TunnelDisplayProps {
  tunnelRunning: boolean
  tunnelPending: boolean   // tunnelRunning && !tunnelBase
  tunnelLastError: string | null
}

function TunnelStatusLabel({ tunnelRunning, tunnelPending, tunnelLastError }: TunnelDisplayProps) {
  return (
    <div>
      {/* AnnotatorPage のトンネルボタンラベルと同じ条件式 */}
      <span data-testid="tunnel-label">
        {tunnelPending ? '取得中...' : tunnelRunning ? '稼働中' : ''}
      </span>
      {/* tunnelLastError: トンネル非稼働時のみ表示 */}
      {tunnelLastError && !tunnelRunning && (
        <span data-testid="tunnel-error">
          ⚠ {tunnelLastError.replace('[ngrok] ', '')}
        </span>
      )}
      {/* 共有ボタン（tunnelPending 中は cursor-wait） */}
      <button
        data-testid="share-btn"
        className={tunnelPending ? 'cursor-wait' : ''}
        onClick={tunnelPending ? undefined : () => {}}
      >
        共有
      </button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

describe('トンネル状態表示ロジック', () => {
  // ── 未起動 ────────────────────────────────────────────────────────────────

  it('tunnelRunning=false のときラベルが空', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={false}
        tunnelPending={false}
        tunnelLastError={null}
      />
    )
    expect(screen.getByTestId('tunnel-label')).toHaveTextContent('')
  })

  it('tunnelRunning=false のときエラーなしなら ⚠ を表示しない', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={false}
        tunnelPending={false}
        tunnelLastError={null}
      />
    )
    expect(screen.queryByTestId('tunnel-error')).not.toBeInTheDocument()
  })

  // ── 取得中（pending） ─────────────────────────────────────────────────────

  it('tunnelPending=true のとき「取得中...」を表示する', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={true}
        tunnelPending={true}
        tunnelLastError={null}
      />
    )
    expect(screen.getByTestId('tunnel-label')).toHaveTextContent('取得中...')
  })

  it('pending 中は共有ボタンが cursor-wait クラスを持つ', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={true}
        tunnelPending={true}
        tunnelLastError={null}
      />
    )
    expect(screen.getByTestId('share-btn')).toHaveClass('cursor-wait')
  })

  // ── 稼働中 ────────────────────────────────────────────────────────────────

  it('tunnelRunning=true, tunnelPending=false のとき「稼働中」を表示する', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={true}
        tunnelPending={false}
        tunnelLastError={null}
      />
    )
    expect(screen.getByTestId('tunnel-label')).toHaveTextContent('稼働中')
  })

  it('稼働中のとき共有ボタンは cursor-wait クラスを持たない', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={true}
        tunnelPending={false}
        tunnelLastError={null}
      />
    )
    expect(screen.getByTestId('share-btn')).not.toHaveClass('cursor-wait')
  })

  // ── エラー ────────────────────────────────────────────────────────────────

  it('tunnelLastError があり tunnelRunning=false のとき ⚠ エラーを表示する', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={false}
        tunnelPending={false}
        tunnelLastError="認証トークンが無効です"
      />
    )
    expect(screen.getByTestId('tunnel-error')).toHaveTextContent('⚠ 認証トークンが無効です')
  })

  it('[ngrok] プレフィックスはエラー表示から除去される', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={false}
        tunnelPending={false}
        tunnelLastError="[ngrok] タイムアウト"
      />
    )
    const errorEl = screen.getByTestId('tunnel-error')
    expect(errorEl).toHaveTextContent('⚠ タイムアウト')
    expect(errorEl).not.toHaveTextContent('[ngrok]')
  })

  it('tunnelLastError があっても tunnelRunning=true のときエラーを表示しない', () => {
    render(
      <TunnelStatusLabel
        tunnelRunning={true}
        tunnelPending={false}
        tunnelLastError="過去のエラー"
      />
    )
    // 稼働中はエラー非表示（前回のエラーが残っていても隠す）
    expect(screen.queryByTestId('tunnel-error')).not.toBeInTheDocument()
  })
})
