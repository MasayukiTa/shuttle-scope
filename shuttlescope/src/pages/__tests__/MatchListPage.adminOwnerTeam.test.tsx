/**
 * 試合登録フォーム: admin の所有チーム指定と保存失敗の表示
 *
 * 背景 (2026-11-11): 試合作成フォームに所有チームの選択欄が無く、owner_team_id を
 * 送っていなかった。チーム未所属の admin は試合を作れず (サーバ 422)、失敗は一瞬の
 * alert のみでフォームを閉じると何も残らなかった。
 *
 * 本テストは実コンポーネント MatchListPage に対して以下を固定する:
 *  - admin かつチーム未所属のとき、所有チーム選択欄が出る
 *  - チームが 1 つだけなら既定で選択され、送信 body に owner_team_id が入る
 *  - チームが 0 件なら案内文を出し、未選択のまま送信すると必須メッセージで止める
 *  - 保存失敗 (422) はフォーム上部に日本語メッセージを出し、フォームを閉じない
 *  - 大会レベル / ラウンド未選択は必須メッセージで止める
 *  - admin 以外 (analyst) には所有チーム欄を出さない
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { UserRole } from '@/types'

// 状態と API モックは vi.hoisted で定義する (vi.mock factory はファイル先頭へ
// ホイストされるため、factory が参照する値もホイスト済みでなければならない)。
const h = vi.hoisted(() => {
  const state = {
    mockRole: 'admin' as UserRole | null,
    mockTeamName: null as string | null,
    teamRows: [] as Array<Record<string, unknown>>,
    apiPostImpl: (async () => ({ success: true, data: { id: 123 } })) as (path: string, body: unknown) => Promise<unknown>,
  }
  // /matches 一覧は空、/auth/teams は可変、/players 系は成功 (検索失敗にしない)
  const apiGet = vi.fn(async (path: string) => {
    if (path === '/matches') return { success: true, data: [] }
    if (path === '/auth/teams') return { success: true, data: state.teamRows }
    if (path === '/players') return { success: true, data: [] }
    if (path === '/players/search') return { success: true, data: [] }
    return { success: true, data: [] }
  })
  // createMatch (apiPost '/matches') の挙動はテストごとに state.apiPostImpl で差し替える
  const apiPost = vi.fn((path: string, body: unknown) => state.apiPostImpl(path, body))
  return { state, apiGet, apiPost }
})
const { apiGet, apiPost } = h

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: h.state.mockRole,
    playerId: 1,
    teamName: h.state.mockTeamName,
    hasRole: (allowed: UserRole[]) =>
      (!h.state.mockRole ? false : h.state.mockRole === 'admin' ? true : allowed.includes(h.state.mockRole)),
    hasPageAccess: () => true,
  }),
}))

vi.mock('@/api/client', () => ({
  // factory はファイル先頭へホイストされるため、ここでは分割代入した const ではなく
  // ホイスト済みの h 経由で mock 関数を参照する (const apiGet は未初期化になるため)。
  apiGet: h.apiGet,
  apiPost: h.apiPost,
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  newIdempotencyKey: () => 'k',
  pipelineJobs: { list: vi.fn(async () => ({ success: true, data: [] })) },
  API_BASE_URL: '',
  listTeams: () => h.apiGet('/auth/teams'),
  // TeamDTO は型のみ (ランタイムでは未使用)
}))

vi.mock('@/components/analysis/PipelineJobBadge', () => ({ PipelineJobBadge: () => null }))
vi.mock('@/components/annotation/QuickStartModal', () => ({ QuickStartModal: () => null }))
vi.mock('@/components/video/DownloadOptionsModal', () => ({ DownloadOptionsModal: () => null }))

import { MatchListPage } from '../MatchListPage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MatchListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// フォームを開き、最低限の必須欄 (レベル / ラウンド / 選手 A・B) を埋める。
// 選手は候補 ID を選ばず名前のみ → provisional として送られる。
async function openFormAndFillRequired(getByText: (t: string) => HTMLElement, getAllByPlaceholderText: (t: string) => HTMLElement[], container: HTMLElement) {
  fireEvent.click(getByText('試合登録'))
  await waitFor(() => expect(container.querySelector('#match-form-level')).not.toBeNull())
  fireEvent.change(container.querySelector('#match-form-level') as HTMLSelectElement, { target: { value: 'IC' } })
  const round = container.querySelector('#match-form-round') as HTMLSelectElement
  // 最初の実ラウンド (disabled でない option) を選ぶ
  const firstRound = Array.from(round.querySelectorAll('option')).find((o) => !o.disabled && o.value) as HTMLOptionElement
  fireEvent.change(round, { target: { value: firstRound.value } })
  const playerInputs = getAllByPlaceholderText('名前を入力して検索...')
  fireEvent.change(playerInputs[0], { target: { value: '選手A' } })
  fireEvent.change(playerInputs[1], { target: { value: '選手B' } })
}

beforeEach(() => {
  h.state.mockRole = 'admin'
  h.state.mockTeamName = null
  h.state.teamRows = []
  apiPost.mockClear()
  apiGet.mockClear()
  h.state.apiPostImpl = async () => ({ success: true, data: { id: 123 } })
})

describe('MatchListPage: admin 所有チーム指定', () => {
  it('admin (チーム未所属): 所有チーム欄が出て、チーム 1 件なら既定選択され owner_team_id を送る', async () => {
    h.state.teamRows = [{ id: 5, uuid: 'u5', display_id: 'T5', name: 'チーム五', short_name: null, is_independent: false, notes: null, created_at: null, updated_at: null }]
    const { getByText, getAllByPlaceholderText, container, getByLabelText } = renderPage()
    await openFormAndFillRequired(getByText, getAllByPlaceholderText, container)

    // 所有チーム選択欄が存在し、1 件なので自動で id=5 が選ばれている
    const sel = getByLabelText('所有チーム（管理者のみ）') as HTMLSelectElement
    await waitFor(() => expect(sel.value).toBe('5'))

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)
    await waitFor(() => expect(apiPost).toHaveBeenCalled())
    const call = apiPost.mock.calls.find((c) => c[0] === '/matches')
    expect(call).toBeTruthy()
    expect((call![1] as Record<string, unknown>).owner_team_id).toBe(5)
  })

  it('admin (チーム未所属): チーム 0 件なら案内文を出し、未選択送信は必須メッセージで止めて POST しない', async () => {
    h.state.teamRows = []
    const { getByText, getAllByPlaceholderText, container, findByText } = renderPage()
    await openFormAndFillRequired(getByText, getAllByPlaceholderText, container)

    // 0 件案内が出る
    expect(await findByText('チームがありません。先にチームを作成してください。')).toBeTruthy()

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)
    // 必須メッセージが出て、/matches への POST は発生しない
    expect(await findByText(/所有チームを選択してください/)).toBeTruthy()
    expect(apiPost.mock.calls.some((c) => c[0] === '/matches')).toBe(false)
  })

  it('保存失敗 (422): フォーム上部に日本語メッセージを出し、フォームを閉じない', async () => {
    h.state.teamRows = [
      { id: 1, uuid: 'u1', display_id: 'A', name: 'Alpha', short_name: null, is_independent: false, notes: null, created_at: null, updated_at: null },
      { id: 2, uuid: 'u2', display_id: 'B', name: 'Bravo', short_name: null, is_independent: false, notes: null, created_at: null, updated_at: null },
    ]
    h.state.apiPostImpl = async (path: string) => {
      if (path === '/matches') {
        const err = new Error('invalid') as Error & { status?: number }
        err.status = 422
        throw err
      }
      return { success: true, data: {} }
    }
    const { getByText, getAllByPlaceholderText, container, getByLabelText, findByRole } = renderPage()
    await openFormAndFillRequired(getByText, getAllByPlaceholderText, container)

    const sel = getByLabelText('所有チーム（管理者のみ）') as HTMLSelectElement
    fireEvent.change(sel, { target: { value: '2' } })

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)
    const alert = await findByRole('alert')
    expect(alert.textContent).toContain('入力内容を確認してください。')
    // フォームは閉じない (所有チーム欄が残っている)
    expect(getByLabelText('所有チーム（管理者のみ）')).toBeTruthy()
  })

  it('大会レベル / ラウンド未選択は必須メッセージで止める', async () => {
    h.state.teamRows = [{ id: 5, uuid: 'u5', display_id: 'T5', name: 'チーム五', short_name: null, is_independent: false, notes: null, created_at: null, updated_at: null }]
    const { getByText, container, findByRole } = renderPage()
    fireEvent.click(getByText('試合登録'))
    await waitFor(() => expect(container.querySelector('#match-form-level')).not.toBeNull())
    // レベル / ラウンド未選択のまま送信
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)
    const alert = await findByRole('alert')
    expect(alert.textContent).toContain('大会レベルを選択してください。')
    expect(apiPost.mock.calls.some((c) => c[0] === '/matches')).toBe(false)
  })

  it('analyst (チーム所属) には所有チーム欄を出さない', async () => {
    h.state.mockRole = 'analyst'
    h.state.mockTeamName = '自チーム'
    h.state.teamRows = []
    const { getByText, container, queryByLabelText } = renderPage()
    fireEvent.click(getByText('試合登録'))
    await waitFor(() => expect(container.querySelector('#match-form-level')).not.toBeNull())
    expect(queryByLabelText('所有チーム（管理者のみ）')).toBeNull()
  })
})
