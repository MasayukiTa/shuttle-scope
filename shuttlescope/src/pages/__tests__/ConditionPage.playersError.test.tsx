/**
 * 監査 #645: Condition の coach / analyst 向け選手一覧 (GET /players) の取得失敗を
 * 「選択候補0件」の正常空状態へ倒さず、明示的なエラー状態と再試行導線を出すことを検証する。
 * players query の isError に応じて QueryErrorNotice が描画されるかを見るため、
 * 既存 inputTabSelector.test.tsx とは別に useQuery をロールごとに出し分ける。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
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

// players query の状態をテストごとに切替える。useQuery は ConditionPage 内で
// players (1 回) しか呼ばれない。history は useConditions フック経由なので別モック。
let mockPlayersQuery: Record<string, unknown> = {}
const refetchPlayers = vi.fn().mockResolvedValue({})
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => mockPlayersQuery,
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: [], isError: false, refetch: vi.fn() }),
  useCreateCondition: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
}))
vi.mock('@/components/tutorial/useTutorial', () => ({ useAutoTutorial: () => {} }))
vi.mock('@/utils/downloadReport', () => ({ downloadReport: vi.fn() }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

vi.mock('@/components/common/SearchableSelect', () => ({
  SearchableSelect: () => <div data-testid="player-selector" />,
}))

const { stub } = vi.hoisted(() => ({
  stub: (name: string) => ({ [name]: () => <div data-testid={`stub-${name}`} /> }),
}))
// QueryErrorNotice は実物を使い、共通の失敗文言 (common_ui.query_failed) と role="alert" を見る。
vi.mock('@/components/condition/WeeklyQuestionnaire', () => stub('WeeklyQuestionnaire'))
vi.mock('@/components/condition/PreMatchQuestionnaire', () => stub('PreMatchQuestionnaire'))
vi.mock('@/components/common/AdviceStrip', () => stub('AdviceStrip'))
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

const queryFailed = lookup(ja as Dict, 'common_ui.query_failed')
const queryRetry = lookup(ja as Dict, 'common_ui.query_retry')

beforeEach(() => {
  mockRole = 'coach'
  mockAuthPlayerId = null
  refetchPlayers.mockClear()
  cleanup()
})

describe('ConditionPage 選手一覧取得失敗 (監査 #645)', () => {
  it('coach: players query が isError のとき、明示的エラーと再試行を出す (空状態に倒さない)', () => {
    mockPlayersQuery = { data: undefined, isError: true, refetch: refetchPlayers }
    render(<ConditionPage />)
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain(queryFailed)
    expect(screen.getByText(queryRetry)).not.toBeNull()
  })

  it('coach: players query 成功かつ 0 件のときはエラーを出さない (正常の空)', () => {
    mockPlayersQuery = { data: { success: true, data: [] }, isError: false, refetch: refetchPlayers }
    render(<ConditionPage />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByTestId('player-selector')).not.toBeNull()
  })

  it('analyst: players query が isError のときも明示的エラーを出す', () => {
    mockRole = 'analyst'
    mockPlayersQuery = { data: undefined, isError: true, refetch: refetchPlayers }
    render(<ConditionPage />)
    expect(screen.getByRole('alert').textContent).toContain(queryFailed)
  })

  it('player: players query は enabled=false 。セレクタ自体が出ずエラーも出さない', () => {
    mockRole = 'player'
    mockAuthPlayerId = 7
    mockPlayersQuery = { data: undefined, isError: false, refetch: refetchPlayers }
    render(<ConditionPage />)
    expect(screen.queryByTestId('player-selector')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
