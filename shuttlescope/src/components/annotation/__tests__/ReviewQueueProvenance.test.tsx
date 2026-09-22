/**
 * 「CV 候補が無い理由」を画面が言えること。
 *
 * バックエンドは `fps_known` / `alignment_failed` を前から成果物に記録して
 * いたが、**画面が一度も読んでいなかった**。出ていたのは「CV候補なし」だけ。
 *
 * A-1b で CV は画像座標から Zone9 を名乗るのをやめた（ネット位置も半面も
 * 画像には入っていない）。その結果 **キャリブレーションが無い試合では
 * 着地ゾーン候補が一件も出ない**。理由が出ないままだと壊れているのと
 * 見分けがつかない。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ReviewQueuePanel } from '../ReviewQueuePanel'
import type { CVCandidatesData } from '@/types/cv'

function data(over: Partial<CVCandidatesData> = {}): CVCandidatesData {
  return {
    match_id: 1,
    built_at: '2026-09-22T00:00:00Z',
    rallies: {},
    calibrated: true,
    player_a_start_side_known: true,
    fps_known: true,
    alignment_failed: null,
    ...over,
  }
}

function panel(d: CVCandidatesData | null) {
  return render(
    <ReviewQueuePanel
      items={[]}
      loading={false}
      onMarkCompleted={() => {}}
      candidatesData={d}
    />,
  )
}

describe('ReviewQueuePanel の来歴表示', () => {
  it('全部そろっていれば何も出さない', () => {
    panel(data())
    expect(screen.queryByText(/CV 補助が効いていない理由/)).toBeNull()
  })

  it('未キャリブレーションを名指しする', () => {
    panel(data({ calibrated: false }))
    expect(screen.getByText(/CV 補助が効いていない理由/)).toBeTruthy()
    expect(screen.getByText(/コートキャリブレーションが未設定/)).toBeTruthy()
  })

  it('開始サイド未設定を名指しする', () => {
    panel(data({ player_a_start_side_known: false }))
    expect(screen.getByText(/player_a の位置が未設定/)).toBeTruthy()
  })

  it('fps 不明とアライメント失敗も出す', () => {
    panel(data({ fps_known: false, alignment_failed: 'boom' }))
    expect(screen.getByText(/fps を推定できませんでした/)).toBeTruthy()
    expect(screen.getByText(/アライメント計算に失敗/)).toBeTruthy()
  })

  it('成果物がまだ無いときは黙っている', () => {
    panel(null)
    expect(screen.queryByText(/CV 補助が効いていない理由/)).toBeNull()
  })

  it('古い成果物（フラグ自体が無い）でも誤報しない', () => {
    // 今日より前に作られた artifact には `calibrated` が入っていない。
    // undefined を「未キャリブレーション」と読むと、全部の試合に警告が出る。
    const legacy = {
      match_id: 1,
      built_at: '2026-09-01T00:00:00Z',
      rallies: {},
    } as CVCandidatesData
    panel(legacy)
    expect(screen.queryByText(/CV 補助が効いていない理由/)).toBeNull()
  })
})
