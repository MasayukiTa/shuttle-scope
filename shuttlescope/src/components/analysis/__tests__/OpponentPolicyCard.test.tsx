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
    global_policy: {
      dominant_shot: 'smash',
      dominant_freq: 0.42,
      entropy: 1.8,
      predictability: 'mixed',
      shot_distribution: { smash: 42, clear: 30, drop: 28 },
      n: 100,
    },
    context_policies: [
      {
        context_key: 'early_short',
        context: { score_phase: 'early', rally_bucket: 'short', zone: null },
        policy: {
          dominant_shot: 'drive',
          dominant_freq: 0.55,
          entropy: 1.2,
          predictability: 'predictable',
          shot_distribution: { drive: 55, drop: 45 },
          n: 20,
        },
      },
    ],
    total_strokes: 100,
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
    expect(await screen.findByText('混合')).toBeInTheDocument()
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
      data: { global_policy: null, context_policies: [], total_strokes: 0 },
      meta: { tier: 'research', evidence_level: 'exploratory', sample_size: 0, caution: null },
    })
    renderCard()
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument()
    expect(screen.getByText(/対戦ストロークデータが不足/)).toBeInTheDocument()
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
        global_policy: {
          ...MOCK_POLICY_RESPONSE.data.global_policy,
          entropy: undefined as any,
        },
      },
    }
    vi.mocked(apiClient.apiGet).mockResolvedValue(respWithUndefinedEntropy)
    renderCard()
    // entropy=0 として 0.00 が表示される
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
        global_policy: {
          ...MOCK_POLICY_RESPONSE.data.global_policy,
          predictability: 'ultra_unpredictable',
        },
      },
    }
    vi.mocked(apiClient.apiGet).mockResolvedValue(resp)
    renderCard()
    // ラベルがなければキー文字列がそのまま表示される
    expect(await screen.findByText('ultra_unpredictable')).toBeInTheDocument()
  })
})
