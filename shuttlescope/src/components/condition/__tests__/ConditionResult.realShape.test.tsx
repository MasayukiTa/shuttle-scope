/**
 * ConditionResult は POST /api/conditions/questionnaire の「実際の応答」のキーを読む。
 * fixtures/questionnaireSubmitResponse.json は backend テスト
 * (backend/tests/test_condition_submit_result_shape.py) の実行結果をそのまま写したもの
 * (admin = 全キー、player = 本人ビュー)。発明したキー名 (ccs / personal_range_low /
 * factors) を読む実装だと、CCS が「—」のまま平常レンジも因子も出ない。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'
import fixture from './fixtures/questionnaireSubmitResponse.json'

type Dict = Record<string, unknown>
let dict: Dict = ja as Dict
let currentRole = 'player'

function lookup(d: Dict, key: string): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], d)
  return typeof v === 'string' ? v : key
}
function interp(s: string, o?: Record<string, unknown>): string {
  return s.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(o?.[k] ?? ''))
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, o?: Record<string, unknown>) => interp(lookup(dict, key), o),
  }),
}))
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ role: currentRole }) }))

import { ConditionResult } from '../ConditionResult'
import type { ConditionResult as ResultType } from '@/hooks/useConditions'

const adminPayload = fixture.admin as unknown as ResultType
const playerPayload = fixture.player as unknown as ResultType

function ccsText(container: HTMLElement): string {
  return container.querySelector('.text-3xl')?.textContent ?? ''
}

describe('ConditionResult: 実応答のキーを読む', () => {
  it('player: CCS・平常レンジ・因子ラベルが出る', () => {
    currentRole = 'player'
    dict = ja as Dict
    const { container } = render(<ConditionResult result={playerPayload} historyCount={9} />)
    expect(ccsText(container)).toBe('80.0')
    const text = container.textContent ?? ''
    // personal_range {low: 75.80, high: 155.30}
    expect(text).toContain('平常レンジ: 75.8 〜 155.3')
    // 平常レンジバー (帯 + 現在値マーカー)
    expect(container.querySelectorAll('.relative.h-3 > div').length).toBe(2)
    // factor_labels は全て caution_mild -> 「少し注意」を 5 因子分
    expect((text.match(/少し注意/g) ?? []).length).toBe(5)
    expect(text).toContain('身体コンディション')
    expect(text).toContain('睡眠・生活')
    // n_28 = 9 (< 28) の文言
    expect(text).toContain('直近9回の平均との差')
  })

  it('CCS が 0..160 の軸に載る (100 で頭打ちにしない)', () => {
    currentRole = 'player'
    const { container } = render(<ConditionResult result={playerPayload} historyCount={9} />)
    const marker = container.querySelector('.relative.h-3 > div.w-1') as HTMLElement
    // 80 / 160 = 50%
    expect(marker.style.left).toBe('calc(50% - 2px)')
    const band = container.querySelector('.relative.h-3 > div.absolute.h-full') as HTMLElement
    expect(parseFloat(band.style.left)).toBeCloseTo((75.8032359555593 / 160) * 100, 3)
    expect(parseFloat(band.style.width)).toBeCloseTo(((155.3078751555518 - 75.8032359555593) / 160) * 100, 3)
  })

  it('player には生スコア・妥当性・弱点表現を出さない (肯定コメントのみ)', () => {
    currentRole = 'player'
    const { container } = render(<ConditionResult result={playerPayload} historyCount={9} />)
    const text = container.textContent ?? ''
    expect(text).toContain(ja.condition.result.positive_comment)
    expect(text).not.toContain('詳細スコア')
    expect(text).not.toContain('回答の妥当性')
    expect(text).not.toMatch(/勝率|弱点/)
  })

  it('admin: 詳細スコア・妥当性レベル・フラグ・回答内訳(JSON文字列を解釈)', () => {
    currentRole = 'admin'
    const { container } = render(<ConditionResult result={adminPayload} historyCount={9} />)
    const text = container.textContent ?? ''
    expect(ccsText(container)).toBe('80.0')
    expect(text).toContain('24.00') // f1_physical
    expect(text).toContain('120.0') // total_score
    // validity_flag は文字列 'caution' (真偽値ではない)。OK/NG にはならない
    expect(text).toContain('回答の妥当性: 要確認')
    expect(text).not.toMatch(/: (OK|NG)/)
    expect(text).toContain('straight_line_response')
    expect(text).toContain('ccs_sudden_change:-80')
    // questionnaire_json は文字列で返る -> 二重エスケープされずオブジェクトとして整形される
    const pre = container.querySelector('pre')?.textContent ?? ''
    expect(pre).toContain('"F1-01": 3')
    expect(pre.startsWith('"')).toBe(false)
  })

  it('coach/analyst 相当の応答 (Tier 2 無し) では「—」と蓄積中。0 や NaN を出さない', () => {
    currentRole = 'coach'
    const tier1: ResultType = { id: 1, player_id: 1, condition_type: 'weekly', validity_flag: 'ok' }
    const { container } = render(<ConditionResult result={tier1} historyCount={0} />)
    const text = container.textContent ?? ''
    expect(ccsText(container)).toBe('—')
    expect(text).toContain('データ蓄積中')
    expect(text).not.toMatch(/NaN|undefined/)
    expect(container.querySelector('.relative.h-3')).toBeNull()
    expect(text).not.toContain('平均との差')
  })

  it('履歴 7 件未満 (範囲・n_28 が null): レンジバーも差も出さず CCS だけ出す', () => {
    currentRole = 'player'
    const r: ResultType = {
      ...playerPayload,
      personal_range: null,
      delta_28ma: null,
      n_28: null,
      factor_labels: {
        f1_physical: 'insufficient_data', f2_stress: 'insufficient_data', f3_mood: 'insufficient_data',
        f4_motivation: 'insufficient_data', f5_sleep_life: 'insufficient_data',
      },
    }
    const { container } = render(<ConditionResult result={r} historyCount={3} />)
    const text = container.textContent ?? ''
    expect(ccsText(container)).toBe('80.0')
    expect(text).toContain('データ蓄積中')
    expect(text).not.toContain('平均との差')
    // insufficient_data を「良好」にしない: 因子セクション自体を出さない
    expect(text).not.toContain('良好')
    expect(text).not.toContain('少し注意')
  })

  it('NaN / 文字列が混ざっても NaN を描かない', () => {
    currentRole = 'player'
    const r = {
      ccs_score: Number.NaN,
      delta_28ma: Number.NaN,
      personal_range: { low: Number.NaN, high: 90 },
      n_28: 0,
    } as unknown as ResultType
    const { container } = render(<ConditionResult result={r} historyCount={Number.NaN} />)
    const text = container.textContent ?? ''
    expect(ccsText(container)).toBe('—')
    expect(text).not.toMatch(/NaN/)
    expect(text).toContain('データ蓄積中')
  })

  it('英語: 因子名・ラベル・妥当性レベルも i18n 経由 (キー名が露出しない)', () => {
    currentRole = 'admin'
    dict = en as Dict
    const { container } = render(<ConditionResult result={adminPayload} historyCount={9} />)
    const text = container.textContent ?? ''
    expect(text).toContain('Physical condition')
    // admin fixture の factor_labels は全て 'caution' -> 表示ラベル 'concern' = "Caution"
    expect((text.match(/Caution(?!\s*flags)/g) ?? []).length).toBeGreaterThanOrEqual(5)
    expect(text).toContain('Response validity: Check')
    expect(text).not.toMatch(/condition\.result\./)
    dict = ja as Dict
  })
})
