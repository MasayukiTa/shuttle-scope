/**
 * G17b #657 (owner 2026-10-31): coach / analyst は入力タブでも選手セレクタを出し、
 * 選択中の選手 (effectivePlayerId) の記録として登録・修正できる
 * （同チーム代理入力；バックエンドの認可は別途）。
 * player はどのタブでもセレクタが出ず (本人固定)、入力も本人 (authPlayerId) のみ。
 * 履歴・分析タブでは従来どおり全ロールでセレクタで誰のデータでも選べる。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import ja from '@/i18n/ja.json'
import type { UserRole } from '@/types'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  return typeof v === 'string' ? v : key
}
function interp(s: string, o?: Record<string, unknown>): string {
  return s.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''))
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown> | string) => {
      const hit = lookup(ja as Dict, key)
      if (hit !== key) return interp(hit, typeof o === 'object' ? o : undefined)
      if (typeof o === 'string') return o
      return key
    },
  }),
}))

let mockRole: UserRole | null = 'coach'
let mockAuthPlayerId: number | null = null
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole, playerId: mockAuthPlayerId }),
}))
vi.mock('@/hooks/useTheme', () => ({ useTheme: () => ({ theme: 'dark' }) }))

const mockPlayers = [
  { id: 11, name: 'Alice', team: 'A', is_target: true },
  { id: 22, name: 'Bob', team: 'A', is_target: false },
]
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: { success: true, data: mockPlayers }, isLoading: false }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

const createMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: [], isError: false, refetch: vi.fn() }),
  useCreateCondition: () => ({ mutateAsync: createMutateAsync, isPending: false }),
}))
vi.mock('@/components/tutorial/useTutorial', () => ({ useAutoTutorial: () => {} }))
vi.mock('@/utils/downloadReport', () => ({ downloadReport: vi.fn() }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

vi.mock('@/components/common/SearchableSelect', () => ({
  SearchableSelect: ({ onChange }: { onChange?: (v: number | null) => void }) => (
    <div data-testid="player-selector">
      <button data-testid="pick-22" onClick={() => onChange && onChange(22)}>pick22</button>
    </div>
  ),
}))

vi.mock('@/components/condition/WeeklyQuestionnaire', () => ({
  WeeklyQuestionnaire: ({ playerId }: { playerId: number }) => (
    <div data-testid="weekly-form" data-player-id={String(playerId)} />
  ),
}))
vi.mock('@/components/condition/PreMatchQuestionnaire', () => ({
  PreMatchQuestionnaire: ({ playerId }: { playerId: number }) => (
    <div data-testid="prematch-form" data-player-id={String(playerId)} />
  ),
}))

const { stub } = vi.hoisted(() => ({
  stub: (name: string) => ({ [name]: () => <div data-testid={`stub-${name}`} /> }),
}))
vi.mock('@/components/common/AdviceStrip', () => stub('AdviceStrip'))
vi.mock('@/components/common/QueryErrorNotice', () => stub('QueryErrorNotice'))
vi.mock('@/components/condition/ConditionGlossary', () => stub('ConditionGlossary'))
vi.mock('@/components/condition/InBodyForm', () => stub('InBodyForm'))
vi.mock('@/components/condition/HooperRpeForm', () => stub('HooperRpeForm'))
vi.mock('@/components/condition/AuxiliaryForm', () => stub('AuxiliaryForm'))
vi.mock('@/components/condition/ConditionResult', () => stub('ConditionResult'))
vi.mock('@/components/condition/GrowthInsights', () => stub('GrowthInsights'))
vi.mock('@/components/condition/BestProfileCard', () => stub('BestProfileCard'))
vi.mock('@/components/condition/CorrelationScatter', () => stub('CorrelationScatter'))
vi.mock('@/components/condition/DiscrepancyAlertList', () => stub('DiscrepancyAlertList'))
vi.mock('@/components/common/CollapsibleSection', () => ({
  CollapsibleSection: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/common/RoleGuard', () => ({
  RoleGuard: ({ children, allowedRoles }: { children?: React.ReactNode; allowedRoles: UserRole[] }) =>
    mockRole && (mockRole === 'admin' || allowedRoles.includes(mockRole)) ? <div>{children}</div> : null,
}))
vi.mock('@/components/condition/ConditionTrendChart', () => stub('ConditionTrendChart'))
vi.mock('@/components/condition/ConditionCorrelationHeatmap', () => stub('ConditionCorrelationHeatmap'))
vi.mock('@/components/condition/ConditionLagCorrelation', () => stub('ConditionLagCorrelation'))
vi.mock('@/components/condition/ConditionOutlierWeeks', () => stub('ConditionOutlierWeeks'))
vi.mock('@/components/condition/ConditionVolatilityRanking', () => stub('ConditionVolatilityRanking'))
vi.mock('@/components/condition/ConditionPCAScatter', () => stub('ConditionPCAScatter'))
vi.mock('@/components/condition/ConditionSeasonality', () => stub('ConditionSeasonality'))
vi.mock('@/components/condition/ConditionGenericScatter', () => stub('ConditionGenericScatter'))
vi.mock('@/components/condition/ConditionPostMatchChange', () => stub('ConditionPostMatchChange'))
vi.mock('@/components/condition/ConditionTagManager', () => stub('ConditionTagManager'))
vi.mock('@/components/condition/ConditionTagCompare', () => stub('ConditionTagCompare'))
vi.mock('@/components/condition/HistoryDetailModal', () => stub('HistoryDetailModal'))
vi.mock('@/components/common/MIcon', () => ({ MIcon: () => <span /> }))

import { ConditionPage } from '../ConditionPage'

const subtabLabel = (k: 'input' | 'history' | 'analytics') => lookup(ja as Dict, `condition.subtab_${k}`)
const modeLabel = (m: 'weekly' | 'prematch' | 'body') => lookup(ja as Dict, `condition.mode.${m}`)

beforeEach(() => {
  mockRole = 'coach'
  mockAuthPlayerId = null
  createMutateAsync.mockClear()
  cleanup()
})

describe('ConditionPage 入力タブの選手セレクタ (G17 #657)', () => {
  it('coach: 既定 (入力タブ) でも選手セレクタを出す', () => {
    render(<ConditionPage />)
    expect(screen.getByTestId('player-selector')).not.toBeNull()
  })

  it('coach: 履歴タブに切替えても選手セレクタが出る', () => {
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(subtabLabel('history')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k1'))).not.toBeNull()
  })

  it('coach: 分析タブに切替えても選手セレクタが出る', () => {
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(subtabLabel('analytics')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k1'))).not.toBeNull()
  })

  it('coach: 分析→入力に戻っても選手セレクタは残る', () => {
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(subtabLabel('analytics')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
    fireEvent.click(screen.getByText(subtabLabel('input')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
  })

  it('analyst: 入力タブでも選手セレクタを出す', () => {
    mockRole = 'analyst'
    render(<ConditionPage />)
    expect(screen.getByTestId('player-selector')).not.toBeNull()
  })

  it('player: どのタブでも選手セレクタは出ない (自分固定)', () => {
    mockRole = 'player'
    mockAuthPlayerId = 7
    render(<ConditionPage />)
    expect(screen.queryByTestId('player-selector')).toBeNull()
    fireEvent.click(screen.getByText(subtabLabel('history')))
    expect(screen.queryByTestId('player-selector')).toBeNull()
  })
})

describe('ConditionPage 入力タブの登録対象 player id (G17b #657)', () => {
  it('coach: 選択中の選手の id でフォームが構成される (週次)', () => {
    mockRole = 'coach'
    mockAuthPlayerId = 99
    render(<ConditionPage />)
    expect(screen.queryByTestId('weekly-form')).toBeNull()
    fireEvent.click(screen.getByTestId('pick-22'))
    const form = screen.getByTestId('weekly-form')
    expect(form.getAttribute('data-player-id')).toBe('22')
  })

  it('player: 自分の id でフォームが構成される', () => {
    mockRole = 'player'
    mockAuthPlayerId = 7
    render(<ConditionPage />)
    const form = screen.getByTestId('weekly-form')
    expect(form.getAttribute('data-player-id')).toBe('7')
  })

  it('coach: 選手未選択では入力できず k1 案内を出す (フォームなし)', () => {
    mockRole = 'coach'
    mockAuthPlayerId = null
    render(<ConditionPage />)
    expect(screen.queryByTestId('weekly-form')).toBeNull()
    expect(screen.queryByTestId('prematch-form')).toBeNull()
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k1'))).not.toBeNull()
  })

  it('coach: body モードの登録は選択中の選手 id で mutateAsync される', async () => {
    mockRole = 'coach'
    mockAuthPlayerId = 99
    render(<ConditionPage />)
    fireEvent.click(screen.getByTestId('pick-22'))
    fireEvent.click(screen.getByText(modeLabel('body')))
    fireEvent.click(screen.getByText(lookup(ja as Dict, 'condition.save')))
    expect(createMutateAsync).toHaveBeenCalledTimes(1)
    // mutateAsync の第 1 引数 (payload) を分解して取り出す。
    const firstCallArgs = createMutateAsync.mock.calls[0] as Array<{ player_id: number }>
    const payload = firstCallArgs[0]
    expect(payload.player_id).toBe(22)
  })
})


describe('ConditionPage 身体データモード (G27 #658 option A)', () => {
  it('player: 自分のページで身体データモードが開ける', () => {
    mockRole = 'player'
    mockAuthPlayerId = 7
    render(<ConditionPage />)
    // モード切替に body ボタンが出る
    const bodyBtn = screen.getByText(modeLabel('body'))
    expect(bodyBtn).not.toBeNull()
    // body モードに切替えると身体データ入力フォームが描画される
    fireEvent.click(bodyBtn)
    expect(screen.getByTestId('stub-InBodyForm')).not.toBeNull()
    expect(screen.getByTestId('stub-HooperRpeForm')).not.toBeNull()
  })

  it('player: body モードの登録は自分の id で mutateAsync される', async () => {
    mockRole = 'player'
    mockAuthPlayerId = 7
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(modeLabel('body')))
    fireEvent.click(screen.getByText(lookup(ja as Dict, 'condition.save')))
    expect(createMutateAsync).toHaveBeenCalledTimes(1)
    const firstCallArgs = createMutateAsync.mock.calls[0] as Array<{ player_id: number }>
    expect(firstCallArgs[0].player_id).toBe(7)
  })

  it('player: 選手レコードに未紐付け (player_id なし) では入力できず案内を出す', () => {
    mockRole = 'player'
    mockAuthPlayerId = null
    render(<ConditionPage />)
    // 身体データフォームも質問票フォームも出ない
    expect(screen.queryByTestId('stub-InBodyForm')).toBeNull()
    expect(screen.queryByTestId('weekly-form')).toBeNull()
    // 未紐付け案内 (k7) を出す
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k7'))).not.toBeNull()
  })

  it('coach: 身体データモードは従来どおり利用でき (選手選択後)、挙動は不変', () => {
    mockRole = 'coach'
    mockAuthPlayerId = 99
    render(<ConditionPage />)
    fireEvent.click(screen.getByTestId('pick-22'))
    fireEvent.click(screen.getByText(modeLabel('body')))
    expect(screen.getByTestId('stub-InBodyForm')).not.toBeNull()
  })

  it('analyst: 身体データモードは従来どおり利用でき (選手選択後)、挙動は不変', () => {
    mockRole = 'analyst'
    mockAuthPlayerId = 99
    render(<ConditionPage />)
    fireEvent.click(screen.getByTestId('pick-22'))
    fireEvent.click(screen.getByText(modeLabel('body')))
    expect(screen.getByTestId('stub-InBodyForm')).not.toBeNull()
  })
})
