/**
 * 監査 #744: OpponentPolicyCard / DoublesRoleCard のラベル・エラー文言・
 * 予測性・ロール・安定性ラベルが t() 経由で出ることを固定する。
 * 以前はこれらはモジュールスコープの Record に日本語直書きされており、
 * 英語 UI でも日本語が残っていた。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ja from '@/i18n/ja.json'
import en from '@/i18n/en.json'

type Dict = Record<string, unknown>
function lookup(dict: Dict, key: string, vars?: Record<string, unknown>): string {
  const v = key.split('.').reduce<unknown>((o, k) => (o as Dict | undefined)?.[k], dict)
  let s = typeof v === 'string' ? v : key
  if (vars) for (const [k, val] of Object.entries(vars)) s = s.replace(new RegExp('{{\\s*' + k + '\\s*}}', 'g'), String(val))
  return s
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, vars?: Record<string, unknown>) => lookup(en as Dict, key, vars),
    i18n: { language: 'en' },
  }),
}))

vi.mock('@/api/client', () => ({ apiGet: vi.fn(), API_BASE_URL: '' }))
vi.mock('@/hooks/useCardTheme', () => ({
  useCardTheme: () => ({
    card: 'card', cardInner: 'ci', cardInnerAlt: 'cia', textHeading: 'th', textSecondary: 'ts',
    textMuted: 'tm', textFaint: 'tf', loading: 'ld', isLight: false,
  }),
}))
vi.mock('@/components/dashboard/EvidenceBadge', () => ({ EvidenceBadge: () => <span /> }))
vi.mock('@/components/dashboard/ResearchNotice', () => ({ ResearchNotice: () => <div /> }))

import * as apiClient from '@/api/client'
import { DEFAULT_FILTERS } from '@/types'
import { OpponentPolicyCard } from '../OpponentPolicyCard'
import { DoublesRoleCard } from '../DoublesRoleCard'

const mockApi = vi.mocked(apiClient.apiGet)

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const OPP_RESP = {
  success: true,
  data: {
    global_policy: { smash: 0.42, clear: 0.3, drop: 0.28 },
    global_entropy: 1.8,
    context_policies: [{
      context_key: 'k', context: { score_phase: 'early', rally_bucket: 'short', zone: null },
      n: 20, shot_distribution: { drive: 1 }, entropy: 1.2,
      dominant_shot: 'drive', dominant_prob: 0.55, predictability: 'mixed',
    }],
    total_opponent_shots: 100, usable_contexts: 1,
  },
  meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 100, caution: null },
}

const ROLE_RESP = {
  success: true,
  data: {
    inferred_role: 'front', confidence_score: 0.8,
    front_ratio: 0.6, back_ratio: 0.3, neutral_ratio: 0.1, total_shots: 50,
    phase_breakdown: [{ score_phase: 'early', inferred_role: 'front', front_ratio: 0.6, back_ratio: 0.3, neutral_ratio: 0.1, n_shots: 10 }],
    note: null,
  },
  meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 50, caution: null },
}

beforeEach(() => { mockApi.mockReset() })

describe('OpponentPolicyCard i18n (#744)', () => {
  it('ラベル・予測性が t() 経由で英語になり、日本語直書きが残らない', async () => {
    mockApi.mockResolvedValue(OPP_RESP as never)
    const { container } = wrap(<OpponentPolicyCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('Mixed'))
    expect(container.textContent).toContain('Early')
    for (const jp of ['序盤', '混合', '予測可能', '予測困難']) {
      expect(container.textContent).not.toContain(jp)
    }
  })

  it('network エラー文言が t() 経由で英語になる', async () => {
    mockApi.mockRejectedValue(new TypeError('Failed to fetch'))
    const { container } = wrap(<OpponentPolicyCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('Network connection failed'))
    expect(container.textContent).not.toContain('ネットワーク接続に失敗')
  })
})

describe('DoublesRoleCard i18n (#744)', () => {
  it('ロールラベルが t() 経由で英語になり、日本語直書きが残らない', async () => {
    mockApi.mockResolvedValue(ROLE_RESP as never)
    const { container } = wrap(<DoublesRoleCard playerId={1} filters={DEFAULT_FILTERS} />)
    await waitFor(() => expect(container.textContent).toContain('Front'))
    expect(container.textContent).toContain('Early')
    for (const jp of ['フロント', 'バック', '序盤']) {
      expect(container.textContent).not.toContain(jp)
    }
  })
})

describe('i18n key parity (#744)', () => {
  const oppKeys = [
    'err_network_title','err_network_hint','err_server_title','err_server_hint','err_unknown_title','err_unknown_hint',
    'phase_early','phase_mid','phase_deuce','phase_endgame','bucket_short','bucket_medium','bucket_long',
    'pred_predictable','pred_mixed','pred_unpredictable','predhint_predictable','predhint_mixed','predhint_unpredictable',
    'caution_fallback','assumptions','promotion','just_now','minutes_ago','hours_ago',
  ]
  const roleKeys = [
    'phase_early','phase_mid','phase_deuce','phase_endgame',
    'role_front','role_back','role_mixed','role_unknown',
    'consistency_consistent','consistency_moderate','consistency_volatile','consistency_insufficient',
  ]
  it('OpponentPolicyCard キーが ja/en 両方にある', () => {
    for (const dict of [ja, en] as Dict[]) for (const k of oppKeys) {
      expect(lookup(dict, 'auto.OpponentPolicyCard.' + k)).not.toBe('auto.OpponentPolicyCard.' + k)
    }
  })
  it('DoublesRoleCard キーが ja/en 両方にある', () => {
    for (const dict of [ja, en] as Dict[]) for (const k of roleKeys) {
      expect(lookup(dict, 'auto.DoublesRoleCard.' + k)).not.toBe('auto.DoublesRoleCard.' + k)
    }
  })
})
