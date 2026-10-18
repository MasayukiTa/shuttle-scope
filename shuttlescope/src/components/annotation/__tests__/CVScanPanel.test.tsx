/**
 * CVScanPanel（動画全体の走査結果の確認パネル）
 *
 * - player / demo / llm には何も描かず、API も呼ばない（admin / analyst / coach のみ）
 * - 区間の表示: データ不足・片側欠けは状態として示し、0 / NaN / undefined の数字を出さない
 * - 採用（adopt）の 409 はサーバの文言をそのまま画面に出す
 * - 決定（reject / accept / assign）は正しい本文で POST される
 * - 走査: 開始・進捗ポーリング・完了後の build・アンマウント時のポーリング停止
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import type { UserRole } from '@/types'

let mockRole: UserRole | null = 'coach'
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) => (!mockRole ? false : mockRole === 'admin' || allowed.includes(mockRole)),
  }),
}))

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('@/api/client', () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
}))

import { CVScanPanel } from '../CVScanPanel'

const MATCH = 7

const SEG_OK = {
  start_sec: 10, end_sec: 20, duration: 10, signal_score: 0.667,
  confidence_basis: 'signals_fired/3', open_ended: false, open_side: null,
  coverage_ratio: 0.9, sample_count: 120, data_status: 'ok', latest_decision: null,
}
const SEG_INSUFFICIENT = {
  start_sec: 30, end_sec: 41.5, duration: 11.5, signal_score: null,
  confidence_basis: 'signals_fired/3', open_ended: false, open_side: null,
  coverage_ratio: 0.2, sample_count: 3, data_status: 'data_insufficient',
  latest_decision: {
    decision_id: 5, start_sec: 30, end_sec: 41.5, action: 'reject', rally_id: null,
    decided_at: '2026-10-18T01:02:03',
  },
}
const SEG_OPEN = {
  start_sec: 50, end_sec: null, duration: null, signal_score: 0.5,
  confidence_basis: 'signals_fired/3', open_ended: true, open_side: 'end_missing',
  coverage_ratio: null, sample_count: null, data_status: 'unverified', latest_decision: null,
}

let segmentsResponse: Record<string, unknown>
let ralliesResponse: Record<string, unknown>

function apiError(status: number, detail: unknown) {
  return Object.assign(new Error(JSON.stringify({ detail })), { status })
}

beforeEach(() => {
  mockRole = 'coach'
  apiGet.mockReset()
  apiPost.mockReset()
  segmentsResponse = {
    success: true,
    data: {
      match_id: MATCH, status: 'ok', sample_fps: 5, sample_count: 500,
      segments: [SEG_OK, SEG_INSUFFICIENT, SEG_OPEN], decisions: [],
    },
  }
  ralliesResponse = {
    success: true,
    data: [
      { id: 101, rally_num: 1, set_id: 1, video_timestamp_start: 0, video_timestamp_end: 0 },
      { id: 102, rally_num: 2, set_id: 1, video_timestamp_start: null, video_timestamp_end: null },
    ],
  }
  apiGet.mockImplementation(async (path: string) => {
    if (path === `/cv-candidates/${MATCH}/segments`) return segmentsResponse
    if (path === `/rallies/match/${MATCH}`) return ralliesResponse
    throw apiError(404, 'not mocked')
  })
})

afterEach(() => {
  vi.useRealTimers()
})

async function openPanel() {
  fireEvent.click(screen.getByRole('button', { name: /動画全体の走査結果/ }))
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith(`/rallies/match/${MATCH}`))
}

describe('CVScanPanel: ロール', () => {
  it.each(['player', 'demo', 'llm'] as UserRole[])('%s には何も描かず API も呼ばない', async (role) => {
    mockRole = role
    const { container } = render(<CVScanPanel matchId={MATCH} />)
    expect(container.innerHTML).toBe('')
    expect(screen.queryByText(/動画全体の走査結果/)).toBeNull()
    await act(async () => { await Promise.resolve() })
    expect(apiGet).not.toHaveBeenCalled()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('未ログイン (role=null) でも描かない', () => {
    mockRole = null
    const { container } = render(<CVScanPanel matchId={MATCH} />)
    expect(container.innerHTML).toBe('')
  })

  it.each(['admin', 'analyst', 'coach'] as UserRole[])('%s には折りたたみの見出しを出し、開くまで API を呼ばない', (role) => {
    mockRole = role
    render(<CVScanPanel matchId={MATCH} />)
    expect(screen.getByRole('button', { name: /動画全体の走査結果/ })).toBeTruthy()
    expect(apiGet).not.toHaveBeenCalled()
  })
})

describe('CVScanPanel: 区間の表示', () => {
  it('通常・データ不足・片側欠けを区別し、0 / NaN / undefined を出さない', async () => {
    const { container } = render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    expect(rows).toHaveLength(3)

    // 通常: mm:ss、signals 2/3、カバー率、未確認
    expect(rows[0].textContent).toContain('00:10 - 00:20')
    expect(rows[0].textContent).toContain('signals 2/3')
    expect(rows[0].textContent).toContain('カバー率 90%')
    expect(rows[0].textContent).toContain('未確認')

    // データ不足: 数字ではなく状態。signals は —
    expect(rows[1].textContent).toContain('データ不足')
    expect(rows[1].textContent).toContain('signals —')
    expect(rows[1].textContent).not.toMatch(/signals\s*\d/)

    // 片側欠け: 終了は「不明」、長さは —（0 ではない）
    expect(rows[2].textContent).toContain('00:50 - 不明')
    expect(rows[2].textContent).toContain('片側欠け（終了が無い）')
    expect(rows[2].textContent).toContain('長さ —')
    expect(rows[2].textContent).toContain('カバー率 —')

    const text = container.textContent ?? ''
    expect(text).not.toMatch(/NaN|undefined|null/)
  })

  it('記録済みの判定（latest_decision）を区間に出す', async () => {
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const dec = await screen.findByTestId('cv-scan-latest-decision')
    expect(dec.textContent).toContain('記録済みの判定: 却下')
  })

  it('status=insufficient_data は理由を出し、区間 0 件を「ラリー無し」と読ませない', async () => {
    segmentsResponse = {
      success: true,
      data: { match_id: MATCH, status: 'insufficient_data', reason: 'ラリー境界の成果物がありません', segments: [], decisions: [] },
    }
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const box = await screen.findByTestId('cv-scan-insufficient')
    expect(box.textContent).toContain('データ不足のため区間を示せません')
    expect(box.textContent).toContain('ラリー境界の成果物がありません')
    expect(screen.queryByTestId('cv-scan-segment')).toBeNull()
    expect(screen.queryByTestId('cv-scan-none')).toBeNull()
  })

  it('status=no_segments は別の文言（データ不足と区別）', async () => {
    segmentsResponse = { success: true, data: { match_id: MATCH, status: 'no_segments', segments: [], decisions: [] } }
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const box = await screen.findByTestId('cv-scan-none')
    expect(box.textContent).toContain('ラリーが無いとは限りません')
    expect(screen.queryByTestId('cv-scan-insufficient')).toBeNull()
  })

  it('区間の読み込み失敗はエラーを出す', async () => {
    apiGet.mockImplementation(async (path: string) => {
      if (path.endsWith('/segments')) throw apiError(500, 'boom')
      return ralliesResponse
    })
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const err = await screen.findByTestId('cv-scan-load-error')
    expect(err.textContent).toContain('boom')
  })

  it('区間の時刻ボタンで onSeek が開始秒で呼ばれる', async () => {
    const onSeek = vi.fn()
    render(<CVScanPanel matchId={MATCH} onSeek={onSeek} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    fireEvent.click(rows[0].querySelector('button')!)
    expect(onSeek).toHaveBeenCalledWith(10)
  })
})

describe('CVScanPanel: 決定と採用', () => {
  it('reject / accept / assign は区間の時刻と action で POST される', async () => {
    apiPost.mockResolvedValue({ success: true, data: {} })
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    const row = rows[0]
    const btn = (name: string) => Array.from(row.querySelectorAll('button')).find((b) => b.textContent === name)!

    fireEvent.click(btn('却下'))
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost).toHaveBeenLastCalledWith(
      `/cv-candidates/${MATCH}/segments/decisions`,
      { start_sec: 10, end_sec: 20, action: 'reject' },
    )

    fireEvent.click(btn('承認'))
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2))
    expect(apiPost).toHaveBeenLastCalledWith(
      `/cv-candidates/${MATCH}/segments/decisions`,
      { start_sec: 10, end_sec: 20, action: 'accept' },
    )

    // ラリー未選択では割り当てできない。選択肢はこの試合の既存ラリーだけ
    expect((btn('割り当て') as HTMLButtonElement).disabled).toBe(true)
    const select = row.querySelector('select') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['', '101', '102'])
    fireEvent.change(select, { target: { value: '102' } })
    fireEvent.click(btn('割り当て'))
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(3))
    expect(apiPost).toHaveBeenLastCalledWith(
      `/cv-candidates/${MATCH}/segments/decisions`,
      { start_sec: 10, end_sec: 20, action: 'assign', rally_id: 102 },
    )
  })

  it('片側欠けの区間の決定は欠けた側を null で送る', async () => {
    apiPost.mockResolvedValue({ success: true, data: {} })
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    const reject = Array.from(rows[2].querySelectorAll('button')).find((b) => b.textContent === '却下')!
    fireEvent.click(reject)
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    expect(apiPost).toHaveBeenLastCalledWith(
      `/cv-candidates/${MATCH}/segments/decisions`,
      { start_sec: 50, end_sec: null, action: 'reject' },
    )
  })

  it('採用は 2 度押して確定し、409 はサーバの文言をそのまま出す', async () => {
    const msg = 'ラリー 101 の開始時刻が既に入力されています（12.5）。人が入れた値は上書きしません'
    apiPost.mockRejectedValue(apiError(409, msg))
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    const row = rows[0]
    const adopt = () => Array.from(row.querySelectorAll('button')).find((b) => /時刻を採用|もう一度押して採用/.test(b.textContent ?? ''))!
    fireEvent.change(row.querySelector('select')!, { target: { value: '101' } })

    fireEvent.click(adopt())
    expect(apiPost).not.toHaveBeenCalled() // 1 度目は確認待ち
    expect(adopt().textContent).toBe('もう一度押して採用')
    fireEvent.click(adopt())
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost).toHaveBeenCalledWith(
      `/cv-candidates/${MATCH}/segments/adopt`,
      { start_sec: 10, end_sec: 20, rally_id: 101 },
    )
    const alert = await screen.findByTestId('cv-scan-row-error')
    expect(alert.textContent).toContain(msg)
    expect(alert.textContent).toContain('採用できませんでした')
  })

  it('採用は成功すると通知し、区間とラリーを読み直す', async () => {
    apiPost.mockResolvedValue({ success: true, data: {} })
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    const row = rows[0]
    fireEvent.change(row.querySelector('select')!, { target: { value: '102' } })
    const before = apiGet.mock.calls.length
    const adopt = () => Array.from(row.querySelectorAll('button')).find((b) => /時刻を採用|もう一度押して採用/.test(b.textContent ?? ''))!
    fireEvent.click(adopt())
    fireEvent.click(adopt())
    await waitFor(() => expect(screen.getByText(/ラリー 102 の動画時刻を採用しました/)).toBeTruthy())
    expect(apiGet.mock.calls.length).toBeGreaterThanOrEqual(before + 2)
  })

  it('データ不足・片側欠けの区間は採用できない', async () => {
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const rows = await screen.findAllByTestId('cv-scan-segment')
    for (const i of [1, 2]) {
      fireEvent.change(rows[i].querySelector('select')!, { target: { value: '101' } })
      const adopt = Array.from(rows[i].querySelectorAll('button')).find((b) => b.textContent === '時刻を採用') as HTMLButtonElement
      expect(adopt.disabled).toBe(true)
    }
  })

  it('ラリーが 1 件も無い試合は割り当て・採用の案内を出す', async () => {
    ralliesResponse = { success: true, data: [] }
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    await screen.findAllByTestId('cv-scan-segment')
    expect((await screen.findAllByText(/既存のラリーがありません/)).length).toBeGreaterThan(0)
  })
})

describe('CVScanPanel: 走査', () => {
  it('開始は 2 度押しで POST し、409 の文言を出す', async () => {
    const msg = 'この試合は既に動画の解析中です (job_id=abcd1234)。'
    apiPost.mockRejectedValue(apiError(409, msg))
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    expect(screen.getByText(/約 30 分/)).toBeTruthy()
    const start = () => screen.getByRole('button', { name: /走査を開始|もう一度押すと開始/ })
    fireEvent.click(start())
    expect(apiPost).not.toHaveBeenCalled()
    fireEvent.click(start())
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(`/cv-candidates/scan/${MATCH}`, {}))
    const err = await screen.findByTestId('cv-scan-start-error')
    expect(err.textContent).toContain(msg)
  })

  it('400 の文言（URL 動画など）もそのまま出す', async () => {
    const msg = 'この試合の動画は URL（外部配信）のため全体走査できません。ローカルファイルの動画が必要です'
    apiPost.mockRejectedValue(apiError(400, msg))
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const start = () => screen.getByRole('button', { name: /走査を開始|もう一度押すと開始/ })
    fireEvent.click(start())
    fireEvent.click(start())
    const err = await screen.findByTestId('cv-scan-start-error')
    expect(err.textContent).toContain(msg)
  })

  it('進捗をポーリングし、完了後に build → 区間の読み直し、アンマウントでポーリング停止', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const statusPhases = [
      { phase: 'tracknet', progress: 0.25, tracknet: { status: 'running', progress: 0.5 }, yolo: { status: 'pending', progress: 0 } },
      { phase: 'done', progress: 1, tracknet: { status: 'done', progress: 1 }, yolo: { status: 'done', progress: 1 } },
    ]
    let polls = 0
    apiGet.mockImplementation(async (path: string) => {
      if (path === `/cv-candidates/${MATCH}/segments`) return segmentsResponse
      if (path === `/rallies/match/${MATCH}`) return ralliesResponse
      if (path === '/cv-candidates/scan-status/job1') {
        const s = statusPhases[Math.min(polls, statusPhases.length - 1)]
        polls += 1
        return { success: true, data: { job_id: 'job1', match_id: MATCH, ...s } }
      }
      throw apiError(404, 'not mocked')
    })
    apiPost.mockImplementation(async (path: string) => {
      if (path === `/cv-candidates/scan/${MATCH}`) return { success: true, data: { job_id: 'job1', match_id: MATCH } }
      if (path === `/cv-candidates/build/${MATCH}`) return { success: true, data: { match_id: MATCH } }
      throw apiError(500, 'unexpected')
    })

    const { unmount } = render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const start = () => screen.getByRole('button', { name: /走査を開始|もう一度押すと開始/ })
    fireEvent.click(start())
    fireEvent.click(start())
    await screen.findByTestId('cv-scan-progress')

    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    await waitFor(() => expect(screen.getByTestId('cv-scan-progress').textContent).toContain('25%'))
    expect(screen.getByTestId('cv-scan-progress').textContent).toContain('TrackNet（シャトル）')

    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    const buildBtn = await screen.findByRole('button', { name: '候補を生成して区間を読み込む' })

    // 完了後はポーリングが止まる
    const pollsAtDone = polls
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(polls).toBe(pollsAtDone)

    const segCallsBefore = apiGet.mock.calls.filter((c) => c[0] === `/cv-candidates/${MATCH}/segments`).length
    fireEvent.click(buildBtn)
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(`/cv-candidates/build/${MATCH}`, {}))
    await waitFor(() =>
      expect(apiGet.mock.calls.filter((c) => c[0] === `/cv-candidates/${MATCH}/segments`).length).toBe(segCallsBefore + 1),
    )
    unmount()
  })

  it('アンマウントすると走査中のポーリングも止まる', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let polls = 0
    apiGet.mockImplementation(async (path: string) => {
      if (path === `/cv-candidates/${MATCH}/segments`) return segmentsResponse
      if (path === `/rallies/match/${MATCH}`) return ralliesResponse
      if (path === '/cv-candidates/scan-status/job2') {
        polls += 1
        return { success: true, data: { job_id: 'job2', match_id: MATCH, phase: 'yolo', progress: 0.6 } }
      }
      throw apiError(404, 'not mocked')
    })
    apiPost.mockResolvedValue({ success: true, data: { job_id: 'job2', match_id: MATCH } })
    const { unmount } = render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const start = () => screen.getByRole('button', { name: /走査を開始|もう一度押すと開始/ })
    fireEvent.click(start())
    fireEvent.click(start())
    await screen.findByTestId('cv-scan-progress')
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(polls).toBe(1)
    unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(polls).toBe(1)
  })

  it('ジョブが 404（消えた）なら失敗として止まる', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    apiGet.mockImplementation(async (path: string) => {
      if (path === `/cv-candidates/${MATCH}/segments`) return segmentsResponse
      if (path === `/rallies/match/${MATCH}`) return ralliesResponse
      throw apiError(404, 'ジョブが見つかりません')
    })
    apiPost.mockResolvedValue({ success: true, data: { job_id: 'gone', match_id: MATCH } })
    render(<CVScanPanel matchId={MATCH} />)
    await openPanel()
    const start = () => screen.getByRole('button', { name: /走査を開始|もう一度押すと開始/ })
    fireEvent.click(start())
    fireEvent.click(start())
    await screen.findByTestId('cv-scan-progress')
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    await waitFor(() => expect(screen.getByTestId('cv-scan-start-error').textContent).toContain('ジョブが見つかりません'))
  })
})
