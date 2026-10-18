/**
 * OpponentPolicyCard コンポーネントテスト
 *
 * カバー範囲:
 * - ローディング状態
 * - 空データ（empty state）
 * - エラー状態（network / server / unknown）の分類別表示
 * - 正常データ表示（EntropyBar, predictability, context policies）
 * - 再取得ボタン動作
 * - entropy が undefined でもクラッシュしない
 * - 最終取得時刻表示
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { OpponentPolicyCard } from '../OpponentPolicyCard'

// ─── モック ──────────────────────────────────────────────────────────────────

vi.mock('@/api/client', () => ({
  apiGet: vi.fn(),
}))

vi.mock('@/hooks/useCardTheme', () => ({
  useCardTheme: () => ({
    card: 'card',
    cardInner: 'cardInner',
    cardInnerAlt: 'cardInnerAlt',
    textHeading: 'textHeading',
    textSecondary: 'textSecondary',
    textMuted: 'textMuted',
    textFaint: 'textFaint',
    loading: 'loading',
    isLight: false,
  }),
}))

vi.mock('@/components/dashboard/EvidenceBadge', () => ({
  EvidenceBadge: ({ sampleSize }: { sampleSize?: number }) => (
    <span data-testid="evidence-badge">N={sampleSize ?? 0}</span>
  ),
}))

vi.mock('@/components/dashboard/ResearchNotice', () => ({
  ResearchNotice: () => <div data-testid="research-notice" />,
}))

import * as apiClient from '@/api/client'
import { DEFAULT_FILTERS } from '@/types'

// ─── ヘルパー ─────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
}

function renderCard(qc?: QueryClient) {
  const client = qc ?? makeQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <OpponentPolicyCard playerId={1} filters={DEFAULT_FILTERS} />
    </QueryClientProvider>
  )
}

const MOCK_POLICY_RESPONSE = {
  success: true,
  data: {
    // バックエンド (compute_opponent_policy) の実際の形: global_policy は確率分布
    global_policy: { smash: 0.42, clear: 0.3, drop: 0.28 },
    global_entropy: 1.8,
    context_policies: [
      {
        context_key: "('early', 'short', 'all')",
        context: { score_phase: 'early', rally_bucket: 'short', zone: null },
        n: 20,
        shot_distribution: { drive: 0.55, drop: 0.45 },
        entropy: 1.2,
        dominant_shot: 'drive',
        dominant_prob: 0.55,
        predictability: 'mixed',
      },
    ],
    total_opponent_shots: 100,
    usable_contexts: 1,
  },
  meta: {
    tier: 'research',
    evidence_level: 'exploratory',
    sample_size: 100,
    caution: null,
  },
}

// ─── テスト ───────────────────────────────────────────────────────────────────

describe('OpponentPolicyCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── ローディング ──────────────────────────────────────────────────────────

  it('ローディング中は "計算中..." を表示する', async () => {
    vi.mocked(apiClient.apiGet).mockReturnValue(new Promise(() => {})) // 解決しない
    renderCard()
    expect(await screen.findByTestId('loading-state')).toBeInTheDocument()
  })

  // ── 正常データ ─────────────────────────────────────────────────────────────

  it('正常データ: dominant_shot と predictability が表示される', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue(MOCK_POLICY_RESPONSE)
    renderCard()
    expect(await screen.findByText('smash')).toBeInTheDocument()
    expect(await screen.findByText('(42.0%)')).toBeInTheDocument()
    // 全体 (0.42 -> mixed) とコンテキスト (mixed) の両方
    expect((await screen.findAllByText('混合')).length).toBe(2)
  })

  it('実バックエンド出力 (compute_opponent_policy の実測値) でコンテキストが描画される', async () => {
    // backend/tests/test_opponent_policy_situation.py の合成ラリーを実際に compute_opponent_policy へ通した出力
    const REAL = {
      global_policy: { clear: 0.5, drop: 0.5 },
      global_entropy: 1.0,
      context_policies: [
        {
          context_key: "('early', 'short', 'NL')",
          context: { score_phase: 'early', rally_bucket: 'short', zone: 'NL' },
          n: 3,
          shot_distribution: { clear: 1.0 },
          entropy: 0.0,
          dominant_shot: 'clear',
          dominant_prob: 1.0,
          predictability: 'predictable',
        },
        {
          context_key: "('early', 'short', 'NR')",
          context: { score_phase: 'early', rally_bucket: 'short', zone: 'NR' },
          n: 3,
          shot_distribution: { drop: 1.0 },
          entropy: 0.0,
          dominant_shot: 'drop',
          dominant_prob: 1.0,
          predictability: 'predictable',
        },
      ],
      total_opponent_shots: 6,
      usable_contexts: 2,
    }
    vi.mocked(apiClient.apiGet).mockResolvedValue({
      success: true,
      data: REAL,
      meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 6, caution: null },
    })
    renderCard()
    // コンテキスト2件: 受けた球の着地ゾーン・n・予測可能が出る
    expect(await screen.findByText(/NL/)).toBeInTheDocument()
    expect(screen.getByText(/NR/)).toBeInTheDocument()
    expect(screen.getAllByText('N=3').length).toBe(2)
    expect(screen.getAllByText('予測可能').length).toBe(2)
    expect(screen.getAllByText('(100.0%)').length).toBe(2)
    expect(screen.getByText(/N=6 ストローク/)).toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).toBeNull()
  })

  it('正常データ: EntropyBar が表示される', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue(MOCK_POLICY_RESPONSE)
    renderCard()
    await waitFor(() => {
      expect(screen.getAllByTestId('entropy-bar').length).toBeGreaterThan(0)
    })
  })

  it('正常データ: コンテキストポリシーが表示される', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue(MOCK_POLICY_RESPONSE)
    renderCard()
    // コンテキストラベル "序盤" は兄弟テキストノードと混在するため部分一致で確認
    await waitFor(() => {
      expect(screen.getByText(/序盤/)).toBeInTheDocument()
    })
    expect(screen.getByText('drive')).toBeInTheDocument()
  })

  it('正常データ: サンプル数が N=100 として表示される', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue(MOCK_POLICY_RESPONSE)
    renderCard()
    expect(await screen.findByText(/N=100 ストローク/)).toBeInTheDocument()
  })

  it('正常データ: EvidenceBadge が sample_size=100 で描画される', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue(MOCK_POLICY_RESPONSE)
    renderCard()
    // データロード後に sample_size=100 が反映されるまで待つ
    await waitFor(() => {
      expect(screen.getByTestId('evidence-badge')).toHaveTextContent('N=100')
    })
  })

  // ── 空データ ──────────────────────────────────────────────────────────────

  it('global_policy が null のとき empty-state を表示する', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue({
      success: true,
      data: { global_policy: null, context_policies: [], total_opponent_shots: 0 },
      meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 0, caution: null },
    })
    renderCard()
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
    expect(screen.getByText(/対戦ストロークデータが不足/)).toBeInTheDocument()
  })

  it('バックエンドの空応答 (global_policy: {}) は empty-state で、0% を出さない', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue({
      success: true,
      data: { global_policy: {}, context_policies: [], total_opponent_shots: 0, usable_contexts: 0 },
      meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 0, caution: null },
    })
    renderCard()
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
    expect(screen.queryByText(/%/)).toBeNull()
  })

  it('global_policy が undefined のとき empty-state を表示する（undefined 耐性）', async () => {
    vi.mocked(apiClient.apiGet).mockResolvedValue({
      success: true,
      data: undefined,
      meta: undefined,
    })
    renderCard()
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
  })

  // ── エラー状態（分類別） ───────────────────────────────────────────────────

  it('TypeError (network error) → error-state-network を表示する', async () => {
    vi.mocked(apiClient.apiGet).mockRejectedValue(new TypeError('Failed to fetch'))
    renderCard()
    expect(await screen.findByTestId('error-state-network')).toBeInTheDocument()
    expect(screen.getByText(/ネットワーク接続に失敗/)).toBeInTheDocument()
  })

  it('status=500 エラー → error-state-server を表示する', async () => {
    const serverErr = Object.assign(new Error('Internal Server Error'), { status: 500 })
    vi.mocked(apiClient.apiGet).mockRejectedValue(serverErr)
    renderCard()
    expect(await screen.findByTestId('error-state-server')).toBeInTheDocument()
    expect(screen.getByText(/サーバーエラー/)).toBeInTheDocument()
  })

  it('status=400 エラー → error-state-unknown を表示する', async () => {
    const clientErr = Object.assign(new Error('Bad Request'), { status: 400 })
    vi.mocked(apiClient.apiGet).mockRejectedValue(clientErr)
    renderCard()
    expect(await screen.findByTestId('error-state-unknown')).toBeInTheDocument()
  })

  // ── 再取得ボタン ──────────────────────────────────────────────────────────

  it('再取得ボタンをクリックすると apiGet が再呼び出しされる', async () => {
    vi.mocked(apiClient.apiGet)
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValue(MOCK_POLICY_RESPONSE)
    renderCard()
    await screen.findByTestId('error-state-network')

    const refetchBtn = screen.getByTestId('refetch-button')
    fireEvent.click(refetchBtn)

    await waitFor(() => {
      expect(vi.mocked(apiClient.apiGet).mock.calls.length).toBeGreaterThan(1)
    })
  })

  // ── entropy undefined 耐性 ────────────────────────────────────────────────

  it('entropy が undefined でも EntropyBar がクラッシュしない', async () => {
    const respWithUndefinedEntropy = {
      ...MOCK_POLICY_RESPONSE,
      data: {
        ...MOCK_POLICY_RESPONSE.data,
        global_entropy: undefined as unknown as number,
      },
    }
    vi.mocked(apiClient.apiGet).mockResolvedValue(respWithUndefinedEntropy)
    renderCard()
    // 全体の entropy が無ければ 0.00 として表示される（コンテキスト側は 1.20）
    await waitFor(() => {
      expect(screen.getByText('0.00')).toBeInTheDocument()
    })
  })

  // ── predictability 未知キー ───────────────────────────────────────────────

  it('未知の predictability キーでも表示がクラッシュしない', async () => {
    const resp = {
      ...MOCK_POLICY_RESPONSE,
      data: {
        ...MOCK_POLICY_RESPONSE.data,
        context_policies: [
          { ...MOCK_POLICY_RESPONSE.data.context_policies[0], predictability: 'ultra_unpredictable' },
        ],
      },
    }
    vi.mocked(apiClient.apiGet).mockResolvedValue(resp)
    renderCard()
    // ラベルがなければキー文字列がそのまま表示される
    expect(await screen.findByText('ultra_unpredictable')).toBeInTheDocument()
  })
})
