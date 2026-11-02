/**
 * 監査項目220: Nが小さく変数数に対し標本が少ない PCA を安定した構造のように見せていた問題への対応。
 * n/p (標本数 / 変数数) が 5 未満のときは参考表示の注記バナー (role="note") を出す。
 * 十分な n/p のときはバナーを出さない。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { UserRole } from '@/types'
import type { ConditionRecord } from '@/hooks/useConditions'

let mockRole: UserRole | null = 'analyst'
let mockData: ConditionRecord[] = []

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    role: mockRole,
    hasRole: (allowed: UserRole[]) =>
      !mockRole ? false : mockRole === 'admin' ? true : allowed.includes(mockRole),
  }),
}))
vi.mock('@/hooks/useConditions', () => ({
  useConditions: () => ({ data: mockData, isLoading: false, isError: false, refetch: () => {} }),
}))

import { ConditionPCAScatter } from '../ConditionPCAScatter'

// 全 9 候補列に値を入れた行 (p=9 になる)
function rowFull(i: number): ConditionRecord {
  const m = (i % 12) + 1
  return {
    id: i,
    player_id: 1,
    measured_at: `2024-${String(m).padStart(2, '0')}-15`,
    condition_type: 'weekly',
    hooper_sleep: 2 + (i % 5),
    hooper_soreness: 1 + (i % 4),
    hooper_stress: 2 + (i % 3),
    hooper_fatigue: 1 + (i % 6),
    session_rpe: 3 + (i % 7),
    sleep_hours: 6 + (i % 3),
    weight_kg: 60 + (i % 5),
    muscle_mass_kg: 50 + (i % 4),
    body_fat_pct: 10 + (i % 6),
  } as ConditionRecord
}

// 3 列のみ値を入れた行 (p=3 になる)
function rowThree(i: number): ConditionRecord {
  const m = (i % 12) + 1
  return {
    id: i,
    player_id: 1,
    measured_at: `2024-${String(m).padStart(2, '0')}-15`,
    condition_type: 'weekly',
    hooper_sleep: 2 + (i % 5),
    hooper_soreness: 1 + (i % 4),
    hooper_stress: 2 + (i % 3),
  } as ConditionRecord
}

beforeEach(() => {
  mockRole = 'analyst'
  mockData = []
})

describe('ConditionPCAScatter low-sample warning (item 220)', () => {
  it('n/p < 5 (16 rows, 9 vars): 参考表示の注記バナーを出す', () => {
    mockData = Array.from({ length: 16 }, (_, i) => rowFull(i))
    const { container } = render(<ConditionPCAScatter playerId={1} isLight={false} />)
    expect(container.querySelector('section')).not.toBeNull()
    expect(container.querySelector('[role="note"]')).not.toBeNull()
  })

  it('n/p >= 5 (60 rows, 3 vars): 注記バナーを出さない', () => {
    mockData = Array.from({ length: 60 }, (_, i) => rowThree(i))
    const { container } = render(<ConditionPCAScatter playerId={1} isLight={false} />)
    expect(container.querySelector('section')).not.toBeNull()
    expect(container.querySelector('[role="note"]')).toBeNull()
  })
})
