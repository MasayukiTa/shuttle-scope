/**
 * G2 #657 (option B, own entry only): 入力タブでは選手セレクタを隠す。
 * 入力は常にログイン本人 (authPlayerId) の記録に限定されるため。
 * 履歴・分析タブでは従来どおりセレクタで誰のデータでも選べる。
 *
 * player ロールはそもそもセレクタが出ない (自分固定) のでここでは
 * coach ロールを中心に検証する。
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
      // t(key) / t(key, defaultString) / t(key, options) を扱う
      const hit = lookup(ja as Dict, key)
      if (hit !== key) return interp(hit, typeof o === 'object' ? o : undefined)
      if (typeof o === 'string') return o
      return key
    },
  }),
}))

// ロールと本人紐付け (authPlayerId) をテストごとに切替える
let mockRole: UserRole | null = 'coach'
let mockAuthPlayerId: number | null = null
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ role: mockRole, playerId: mockAuthPlayerId }),
}))
vi.mock('@/hooks/useTheme', () => ({ useTheme: () => ({ theme: 'dark' }) }))

// react-query: /players は coach/analyst のみ enabled。最小ダミーを返す。
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: { success: true, data: [] }, isLoading: false }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: [], isError: false, refetch: vi.fn() }),
  useCreateCondition: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('@/components/tutorial/useTutorial', () => ({ useAutoTutorial: () => {} }))
vi.mock('@/utils/downloadReport', () => ({ downloadReport: vi.fn() }))
vi.mock('@/api/client', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

// 選手セレクタは testid で存在を判定できるよう差し替える。
vi.mock('@/components/common/SearchableSelect', () => ({
  SearchableSelect: () => <div data-testid="player-selector" />,
}))

// 重い/無関係な子コンポーネントは空スタブにする。
const stub = (name: string) => ({ [name]: () => <div data-testid={`stub-${name}`} /> })
vi.mock('@/components/common/AdviceStrip', () => stub('AdviceStrip'))
vi.mock('@/components/common/QueryErrorNotice', () => stub('QueryErrorNotice'))
vi.mock('@/components/condition/ConditionGlossary', () => stub('ConditionGlossary'))
vi.mock('@/components/condition/InBodyForm', () => stub('InBodyForm'))
vi.mock('@/components/condition/HooperRpeForm', () => stub('HooperRpeForm'))
vi.mock('@/components/condition/AuxiliaryForm', () => stub('AuxiliaryForm'))
vi.mock('@/components/condition/WeeklyQuestionnaire', () => stub('WeeklyQuestionnaire'))
vi.mock('@/components/condition/PreMatchQuestionnaire', () => stub('PreMatchQuestionnaire'))
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

beforeEach(() => {
  mockRole = 'coach'
  mockAuthPlayerId = null
  cleanup()
})

describe('ConditionPage 入力タブの選手セレクタ (G2 #657)', () => {
  it('coach: 既定 (入力タブ) では選手セレクタを出さない', () => {
    render(<ConditionPage />)
    expect(screen.queryByTestId('player-selector')).toBeNull()
  })

  it('coach: 履歴タブに切替えると選手セレクタが出る', () => {
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(subtabLabel('history')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k1'))).not.toBeNull()
  })

  it('coach: 分析タブに切替えると選手セレクタが出る', () => {
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(subtabLabel('analytics')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k1'))).not.toBeNull()
  })

  it('coach: 分析→入力に戻ると再び選手セレクタは消える', () => {
    render(<ConditionPage />)
    fireEvent.click(screen.getByText(subtabLabel('analytics')))
    expect(screen.getByTestId('player-selector')).not.toBeNull()
    fireEvent.click(screen.getByText(subtabLabel('input')))
    expect(screen.queryByTestId('player-selector')).toBeNull()
  })

  it('player: どのタブでも選手セレクタは出ない (自分固定)', () => {
    mockRole = 'player'
    mockAuthPlayerId = 7
    render(<ConditionPage />)
    expect(screen.queryByTestId('player-selector')).toBeNull()
    fireEvent.click(screen.getByText(subtabLabel('history')))
    expect(screen.queryByTestId('player-selector')).toBeNull()
  })

  it('coach (本人紐付けなし): 入力タブでは本人記録限定の案内を出し、k1 は出さない', () => {
    mockRole = 'coach'
    mockAuthPlayerId = null
    render(<ConditionPage />)
    // 入力タブ: 選手未選択でも「選手を選んでください (k1)」ではなく
    // 本人記録限定の案内 (k7) を出す。
    expect(screen.queryByText(lookup(ja as Dict, 'auto.ConditionPage.k1'))).toBeNull()
    expect(screen.getByText(lookup(ja as Dict, 'auto.ConditionPage.k7'))).not.toBeNull()
  })
})
