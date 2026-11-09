/**
 * 確認モード (F-T003-03): 実データ接続後の挙動。
 *
 * 旧テストは廃止した `connected` / 件数バッジ (境界候補・ID紐付・Swing) の
 * 「未接続（開発中）」表示を検証していたが、確認タブは保存済みラリー/ストロークの
 * 実データ表示・編集に置き換わった。ここでは:
 *  - matchId 未指定: API を呼ばず案内 (review_no_match) を出す
 *  - matchId 指定: ラリー→ストロークを取得して表示し、編集で updateStroke を呼ぶ
 * react-i18next はキーをそのまま返すモックにしているので、文言ではなく
 * i18n キーで検証する。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { ReviewModePanel } from '../ReviewModePanel'

vi.mock('@/components/common/MIcon', () => ({
  MIcon: () => null,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('@/api/review', () => ({
  getMatchRallies: vi.fn(),
  getRallyStrokes: vi.fn(),
  updateStroke: vi.fn(),
}))

import * as reviewApi from '@/api/review'

const mockGetRallies = reviewApi.getMatchRallies as unknown as ReturnType<typeof vi.fn>
const mockGetStrokes = reviewApi.getRallyStrokes as unknown as ReturnType<typeof vi.fn>
const mockUpdateStroke = reviewApi.updateStroke as unknown as ReturnType<typeof vi.fn>

const RALLY = {
  id: 7,
  uuid: 'u7',
  set_id: 1,
  rally_num: 3,
  server: 'player_a',
  winner: 'player_a',
  end_type: 'smash_winner',
  rally_length: 5,
  duration_sec: 12,
  score_a_after: 5,
  score_b_after: 4,
  is_deuce: false,
  video_timestamp_start: null,
  video_timestamp_end: null,
}

const STROKE = {
  id: 101,
  rally_id: 7,
  stroke_num: 1,
  player: 'player_a',
  shot_type: 'serve',
  shot_quality: null,
  hit_zone: null,
  land_zone: 'rear_left',
  contact_height: 'underhand',
  intent_tag: 'deep',
  intent_note: 'keep deep',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReviewModePanel 実データ接続 (F-T003-03)', () => {
  it('matchId 未指定なら API を呼ばず案内を出す', () => {
    render(<ReviewModePanel matchId={null} />)
    expect(screen.getByText('annotator.ux.review_no_match')).toBeTruthy()
    expect(mockGetRallies).not.toHaveBeenCalled()
  })

  it('matchId 指定でラリー一覧を取得して表示する', async () => {
    mockGetRallies.mockResolvedValue([RALLY])
    render(<ReviewModePanel matchId={42} />)
    await waitFor(() => {
      expect(mockGetRallies).toHaveBeenCalledWith(42)
    })
    expect(screen.getByText('annotator.ux.review_rally_label')).toBeTruthy()
  })

  it('ラリーを開くとストロークを取得し、編集で updateStroke を呼ぶ', async () => {
    mockGetRallies.mockResolvedValue([RALLY])
    mockGetStrokes.mockResolvedValue([STROKE])
    mockUpdateStroke.mockResolvedValue({ ...STROKE, shot_type: 'smash' })
    render(<ReviewModePanel matchId={42} />)

    await waitFor(() => expect(screen.getByText('annotator.ux.review_rally_label')).toBeTruthy())
    fireEvent.click(screen.getByText('annotator.ux.review_rally_label'))

    await waitFor(() => expect(mockGetStrokes).toHaveBeenCalledWith(7))
    // 編集フォームを開く
    fireEvent.click(screen.getByText('annotator.ux.review_edit'))
    // 保存
    fireEvent.click(screen.getByText('annotator.ux.review_save'))
    await waitFor(() => expect(mockUpdateStroke).toHaveBeenCalledTimes(1))
    const [idArg] = mockUpdateStroke.mock.calls[0]
    expect(idArg).toMatchObject({ id: 101, stroke_num: 1, player: 'player_a' })
  })

  it('ラリー取得失敗で再試行ボタンを出す', async () => {
    mockGetRallies.mockRejectedValue(new Error('network down'))
    render(<ReviewModePanel matchId={42} />)
    await waitFor(() => {
      expect(screen.getByText('annotator.ux.review_retry')).toBeTruthy()
    })
    const callsBefore = mockGetRallies.mock.calls.length
    fireEvent.click(screen.getByText('annotator.ux.review_retry'))
    await waitFor(() => {
      expect(mockGetRallies.mock.calls.length).toBeGreaterThan(callsBefore)
    })
  })
})
