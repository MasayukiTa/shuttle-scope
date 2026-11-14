/**
 * Part 2(a) / intent-memo i18n: the Review tab edit panel must show the
 * intent-tag choices with the SAME i18n keys (enrichment.intent_tag_*) that
 * the input screen uses, instead of the raw internal values (deep / net /
 * body / sideline / cross / deception / clear_safe / other).
 * The saved value (the option's value attribute) stays the internal value.
 * The read-only summary line also shows the translated label, not the raw tag.
 *
 * Rendering follows the same style as ReviewModePanel.hitHeightLabels.test.tsx
 * (API mocked, i18n initialised to ja in test-setup.ts).
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

// internal value (saved value) -> expected translated label shared with the input screen
const EXPECTED: Array<{ value: string; label: string }> = [
  { value: 'deep', label: ja.enrichment.intent_tag_deep },
  { value: 'net', label: ja.enrichment.intent_tag_net },
  { value: 'body', label: ja.enrichment.intent_tag_body },
  { value: 'sideline', label: ja.enrichment.intent_tag_sideline },
  { value: 'cross', label: ja.enrichment.intent_tag_cross },
  { value: 'deception', label: ja.enrichment.intent_tag_deception },
  { value: 'clear_safe', label: ja.enrichment.intent_tag_clear_safe },
  { value: 'other', label: ja.enrichment.intent_tag_other },
]

const RAW_TAGS = ['deep', 'net', 'body', 'sideline', 'cross', 'deception', 'clear_safe', 'other']

async function openIntentSelect(): Promise<HTMLSelectElement> {
  mockGetRallies.mockResolvedValue([RALLY])
  mockGetStrokes.mockResolvedValue([STROKE])
  render(<ReviewModePanel matchId={42} />)
  fireEvent.click(await screen.findByText('ラリー 3'))
  await waitFor(() => expect(mockGetStrokes).toHaveBeenCalledWith(7))
  fireEvent.click(await screen.findByText('編集'))
  const label = await screen.findByText(ja.annotator.ux.review_f_intent)
  const select = label.parentElement?.querySelector('select') as HTMLSelectElement
  expect(select).toBeTruthy()
  return select
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Review tab intent-tag choices (Part 2a intent-memo i18n)', () => {
  it('shows the eight choices with the same translated labels as the input screen', async () => {
    const select = await openIntentSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const real = options.filter((o) => o.value !== '')
    expect(real.map((o) => o.textContent)).toEqual(EXPECTED.map((e) => e.label))
  })

  it('keeps the saved value (option value) as the internal value', async () => {
    const select = await openIntentSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const real = options.filter((o) => o.value !== '')
    expect(real.map((o) => o.value)).toEqual(EXPECTED.map((e) => e.value))
  })

  it('never shows the raw internal tags (deep/net/body/...) as a label', async () => {
    const select = await openIntentSelect()
    const options = within(select).getAllByRole('option') as HTMLOptionElement[]
    const joined = options.map((o) => o.textContent ?? '').join('|')
    for (const raw of RAW_TAGS) {
      expect(joined).not.toContain(raw)
    }
  })

  it('shows the translated intent tag (not the raw value) in the read-only summary', async () => {
    mockGetRallies.mockResolvedValue([RALLY])
    mockGetStrokes.mockResolvedValue([STROKE])
    render(<ReviewModePanel matchId={42} />)
    fireEvent.click(await screen.findByText('ラリー 3'))
    await waitFor(() => expect(mockGetStrokes).toHaveBeenCalledWith(7))
    const intentLabel = `${ja.annotator.ux.review_f_intent}: ${ja.enrichment.intent_tag_deep}`
    expect(await screen.findByText(intentLabel)).toBeTruthy()
  })
})
