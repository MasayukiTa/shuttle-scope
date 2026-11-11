/**
 * F-T003-06 / 顧客 要望#8: 確認タブの編集欄で「打点の高さ」の
 * 選択肢が、入力画面と同じ i18n キー (enrichment.contact_height_*) の
 * 訳語 (ネットより上 / やや上 / やや下 / 下) で表示されることを検証する。
 * 保存値 (option の value: overhead/side/underhand/scoop) は内部値のまま不変。
 *
 * レンダリングは ReviewModePanel.realdata.test.tsx と同じ流儀
 * (API モック、i18n は test-setup.ts で ja 初期化済み)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import ja from '@/i18n/ja.json'
import { ReviewModePanel } from '../ReviewModePanel'

vi.mock('@/components/common/MIcon', () => ({
  MIcon: () => null,
}))

vi.mock('@/api/review', () => ({
  getMatchRallies: vi.fn(),
  getRallyStrokes: vi.fn(),
  updateStroke: vi.fn(),
}))

import * as reviewApi from '@/api/review'

const mockGetRallies = reviewApi.getMatchRallies as unknown as ReturnType<typeof vi.fn>
const mockGetStrokes = reviewApi.getRallyStrokes as unknown as ReturnType<typeof vi.fn>

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

// 内部値 (保存値) -> 入力画面と共通の i18n キーの期待訳語
const EXPECTED: Array<{ value: string; label: string }> = [
  { value: 'overhead', label: ja.enrichment.contact_height_overhead },
  { value: 'side', label: ja.enrichment.contact_height_side },
  { value: 'underhand', label: ja.enrichment.contact_height_underhand },
  { value: 'scoop', label: ja.enrichment.contact_height_scoop },
]

async function openHeightSelect(): Promise<HTMLSelectElement> {
  mockGetRallies.mockResolvedValue([RALLY])
  mockGetStrokes.mockResolvedValue([STROKE])
  render(<ReviewModePanel matchId={42} />)
  fireEvent.click(await screen.findByText('ラリー 3'))
  await waitFor(() => expect(mockGetStrokes).toHaveBeenCalledWith(7))
  fireEvent.click(await screen.findByText('編集'))
  const label = await screen.findByText(ja.annotator.ux.review_f_height)
  const select = label.parentElement?.querySelector('select') as HTMLSelectElement
  expect(select).toBeTruthy()
  return select
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('確認タブの打点の高さの選択肢 (F-T003-06, 顧客 要望#8)', () => {
  it('4つの選択肢の表示名が入力画面と同じ訳語になる', async () => {
    const select = await openHeightSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const real = options.filter((o) => o.value !== '')
    expect(real.map((o) => o.textContent)).toEqual(EXPECTED.map((e) => e.label))
  })

  it('保存される値 (option の value) は内部値のまま変わらない', async () => {
    const select = await openHeightSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const real = options.filter((o) => o.value !== '')
    expect(real.map((o) => o.value)).toEqual(EXPECTED.map((e) => e.value))
  })

  it('表示名に技術名 (overhead/side/underhand/scoop) が生のまま出ない', async () => {
    const select = await openHeightSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const joined = options.map((o) => o.textContent ?? '').join('|')
    for (const raw of ['overhead', 'side', 'underhand', 'scoop']) {
      expect(joined).not.toContain(raw)
    }
  })

  it('最も高い打点は「ネットより上」、最も低い打点は「ネットより下」', async () => {
    const select = await openHeightSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const real = options.filter((o) => o.value !== '')
    const first = real[0]
    const last = real[real.length - 1]
    expect(first.value).toBe('overhead')
    expect(first.textContent).toBe('ネットより上')
    expect(last.value).toBe('scoop')
    expect(last.textContent).toBe('ネットより下')
  })
})
