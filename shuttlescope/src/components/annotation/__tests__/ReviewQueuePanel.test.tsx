/**
 * ReviewQueuePanel コンポーネントテスト
 *
 * カバー範囲:
 * - 空キュー（「要確認なし」表示）
 * - pending アイテムの一覧表示
 * - reason code のカテゴリ別展開（データ / 品質）
 * - 信頼度サマリー（candidatesData がある場合）
 * - 「完了」ボタン → onMarkCompleted コールバック
 * - completed アイテムのトグル表示
 * - loading スピナー
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { ReviewQueuePanel } from '../ReviewQueuePanel'
import type { ReviewQueueItem, CVCandidatesData } from '@/types/cv'

// ── テストデータ ─────────────────────────────────────────────────────────────

function makeItem(overrides: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    rally_id: 1,
    rally_num: 3,
    set_id: 1,
    review_status: 'pending',
    cv_reason_codes: [],
    ...overrides,
  }
}

function makeCandidatesData(
  rallyId: number,
  landZoneFillRate: number,
  hitterFillRate: number
): CVCandidatesData {
  return {
    match_id: 1,
    built_at: '2026-04-10T00:00:00',
    rallies: {
      [String(rallyId)]: {
        rally_id: rallyId,
        cv_assist_available: true,
        cv_confidence_summary: {
          land_zone_fill_rate: landZoneFillRate,
          hitter_fill_rate: hitterFillRate,
          avg_confidence: (landZoneFillRate + hitterFillRate) / 2,
        },
        front_back_role_signal: null,
        review_reason_codes: [],
        strokes: [],
      },
    },
  }
}

// ─────────────────────────────────────────────────────────────────────────────

describe('ReviewQueuePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── 空状態 ────────────────────────────────────────────────────────────────

  it('pending アイテムが 0 件のとき「要確認なし」を表示する', () => {
    render(
      <ReviewQueuePanel
        items={[]}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    expect(screen.getByText(/要確認なし/)).toBeInTheDocument()
  })

  it('loading=true のときスピナーが表示される', () => {
    render(
      <ReviewQueuePanel
        items={[]}
        loading={true}
        onMarkCompleted={vi.fn()}
      />
    )
    // RefreshCw アイコン（animate-spin クラス）が存在する
    const spinner = document.querySelector('.animate-spin')
    expect(spinner).toBeInTheDocument()
  })

  // ── pending アイテム ──────────────────────────────────────────────────────

  it('pending アイテムのラリー番号を表示する', () => {
    render(
      <ReviewQueuePanel
        items={[makeItem({ rally_num: 5 })]}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    expect(screen.getByText('R5')).toBeInTheDocument()
  })

  it('件数バッジに pending 数を表示する', () => {
    const items = [
      makeItem({ rally_id: 1, rally_num: 1 }),
      makeItem({ rally_id: 2, rally_num: 2 }),
    ]
    render(
      <ReviewQueuePanel
        items={items}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    expect(screen.getByText('2 件')).toBeInTheDocument()
  })

  // ── 完了ボタン ────────────────────────────────────────────────────────────

  it('「完了」ボタンをクリックすると onMarkCompleted が rally_id で呼ばれる', () => {
    const onMarkCompleted = vi.fn()
    render(
      <ReviewQueuePanel
        items={[makeItem({ rally_id: 7, rally_num: 3 })]}
        loading={false}
        onMarkCompleted={onMarkCompleted}
      />
    )
    fireEvent.click(screen.getByText('完了'))
    expect(onMarkCompleted).toHaveBeenCalledWith(7)
  })

  // ── 移動ボタン ────────────────────────────────────────────────────────────

  it('onJumpToRally がある場合「移動」ボタンを表示する', () => {
    render(
      <ReviewQueuePanel
        items={[makeItem()]}
        loading={false}
        onMarkCompleted={vi.fn()}
        onJumpToRally={vi.fn()}
      />
    )
    expect(screen.getByText('移動')).toBeInTheDocument()
  })

  it('「移動」ボタンをクリックすると onJumpToRally が呼ばれる', () => {
    const onJump = vi.fn()
    render(
      <ReviewQueuePanel
        items={[makeItem({ rally_id: 4, rally_num: 7 })]}
        loading={false}
        onMarkCompleted={vi.fn()}
        onJumpToRally={onJump}
      />
    )
    fireEvent.click(screen.getByText('移動'))
    expect(onJump).toHaveBeenCalledWith(4, 7)
  })

  it('onJumpToRally がない場合「移動」ボタンを表示しない', () => {
    render(
      <ReviewQueuePanel
        items={[makeItem()]}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    expect(screen.queryByText('移動')).not.toBeInTheDocument()
  })

  // ── 理由コード展開 ────────────────────────────────────────────────────────

  it('理由コードがある場合、折りたたまれた状態でラベルが表示される', () => {
    render(
      <ReviewQueuePanel
        items={[makeItem({ cv_reason_codes: ['low_frame_coverage'] })]}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    // トグルボタンにラベルが含まれる（折りたたみ状態）
    expect(screen.getByText(/フレーム不足/)).toBeInTheDocument()
  })

  it('展開トグルをクリックするとカテゴリ別理由が表示される', () => {
    render(
      <ReviewQueuePanel
        items={[makeItem({ cv_reason_codes: ['low_frame_coverage', 'hitter_undetected'] })]}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    // トグルボタンをクリック（折りたたみ状態のボタンは getAllByText で取得）
    const toggleBtns = screen.getAllByText(/フレーム不足/)
    fireEvent.click(toggleBtns[0])
    // 展開後: データカテゴリラベルが追加で表示される
    expect(screen.getByText('データ:')).toBeInTheDocument()
    // 品質カテゴリ（複数マッチを避けるためカテゴリ行内で確認）
    const qualityLabel = screen.getByText('品質:')
    expect(qualityLabel).toBeInTheDocument()
    expect(qualityLabel.parentElement).toHaveTextContent('打者不明')
  })

  // ── 信頼度サマリー（candidatesData） ─────────────────────────────────────

  it('candidatesData がある場合、信頼度ピルを表示する', () => {
    const candidatesData = makeCandidatesData(1, 0.80, 0.50)
    render(
      <ReviewQueuePanel
        items={[makeItem({ rally_id: 1 })]}
        loading={false}
        onMarkCompleted={vi.fn()}
        candidatesData={candidatesData}
      />
    )
    // 着地 80% / 打者 50%
    expect(screen.getByTitle('着地: 80%')).toBeInTheDocument()
    expect(screen.getByTitle('打者: 50%')).toBeInTheDocument()
  })

  it('candidatesData がない場合、信頼度ピルを表示しない', () => {
    render(
      <ReviewQueuePanel
        items={[makeItem({ rally_id: 1 })]}
        loading={false}
        onMarkCompleted={vi.fn()}
      />
    )
    expect(screen.queryByTitle(/着地/)).not.toBeInTheDocument()
  })

  // ── completed アイテム ────────────────────────────────────────────────────

  it('completed アイテムは pending リストに含まれない', () => {
    const items = [
      makeItem({ rally_id: 1, rally_num: 1, review_status: 'completed' }),
      makeItem({ rally_id: 2, rally_num: 2, review_status: 'pending' }),
    ]
    render(
      <ReviewQueuePanel items={items} loading={false} onMarkCompleted={vi.fn()} />
    )
    // pending が 1件なので件数バッジは 1
    expect(screen.getByText('1 件')).toBeInTheDocument()
  })

  it('completed アイテムがある場合「完了済み N 件」トグルが表示される', () => {
    const items = [
      makeItem({ rally_id: 1, rally_num: 1, review_status: 'completed' }),
    ]
    render(
      <ReviewQueuePanel items={items} loading={false} onMarkCompleted={vi.fn()} />
    )
    expect(screen.getByText(/完了済み 1 件/)).toBeInTheDocument()
  })

  it('「完了済み N 件」トグルをクリックすると完了ラリーが表示される', () => {
    const items = [
      makeItem({ rally_id: 1, rally_num: 9, review_status: 'completed' }),
    ]
    render(
      <ReviewQueuePanel items={items} loading={false} onMarkCompleted={vi.fn()} />
    )
    fireEvent.click(screen.getByText(/完了済み 1 件/))
    expect(screen.getByText('R9')).toBeInTheDocument()
  })
})
