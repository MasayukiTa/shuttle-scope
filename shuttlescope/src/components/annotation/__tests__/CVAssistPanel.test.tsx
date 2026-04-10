/**
 * CVAssistPanel コンポーネントテスト
 *
 * カバー範囲:
 * - rallyCandidates=null のとき「CV候補なし」を表示する
 * - サマリーバー（着地・打者フィルレート）の表示
 * - ストロークごとの候補行レンダリング（land_zone / hitter）
 * - 信頼度 % の色分け（auto_filled=emerald / suggested=blue / review_required=amber）
 * - ソースラベル（TN / YOLO / ALN / FUS）の表示
 * - ✓ 承認ボタン（suggested のみ表示）
 * - 理由コード展開トグル（ChevronRight → ChevronDown）
 * - ダブルスロール（front_back_role_signal）の表示
 * - 要確認理由コードのカテゴリ別表示
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CVAssistPanel } from '../CVAssistPanel'
import type { RallyCVCandidate } from '@/types/cv'

// react-i18next モック（StrokeRow 内で useTranslation を使用）
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback: string) => fallback,
  }),
}))

// ── テストデータ ─────────────────────────────────────────────────────────────

function makeRallyCandidate(overrides: Partial<RallyCVCandidate> = {}): RallyCVCandidate {
  return {
    rally_id: 1,
    cv_assist_available: true,
    cv_confidence_summary: {
      land_zone_fill_rate: 0.80,
      hitter_fill_rate: 0.60,
      avg_confidence: 0.70,
    },
    front_back_role_signal: null,
    review_reason_codes: [],
    strokes: [
      {
        stroke_id: 101,
        stroke_num: 1,
        timestamp_sec: 1.0,
        land_zone: {
          value: 'BL',
          confidence_score: 0.85,
          source: 'tracknet',
          decision_mode: 'auto_filled',
          reason_codes: ['track_present_high_confidence'],
        },
        hitter: {
          value: 'player_a',
          confidence_score: 0.75,
          source: 'alignment',
          decision_mode: 'auto_filled',
          reason_codes: [],
        },
        front_back_role: null,
      },
    ],
    ...overrides,
  }
}

// ─────────────────────────────────────────────────────────────────────────────

describe('CVAssistPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── null 状態 ──────────────────────────────────────────────────────────────

  it('rallyCandidates=null のとき「CV 候補なし」を表示する', () => {
    render(<CVAssistPanel rallyCandidates={null} />)
    expect(screen.getByText(/CV 候補なし/)).toBeInTheDocument()
  })

  // ── サマリーバー ───────────────────────────────────────────────────────────

  it('着地ゾーンのフィルレートを % 表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    // land_zone_fill_rate=0.80 → 80%
    expect(screen.getByText('80%')).toBeInTheDocument()
  })

  it('打者のフィルレートを % 表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    // hitter_fill_rate=0.60 → 60%
    expect(screen.getByText('60%')).toBeInTheDocument()
  })

  it('平均信頼度 > 0 のとき平均信頼度を表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    // avg_confidence=0.70 → 70%
    expect(screen.getByText(/平均信頼度/)).toBeInTheDocument()
  })

  // ── ストロークフィールド表示 ────────────────────────────────────────────────

  it('ストローク番号 (#1) を表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.getByText('#1')).toBeInTheDocument()
  })

  it('着地ゾーンの値 (BL) を表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.getByText('BL')).toBeInTheDocument()
  })

  it('着地ゾーンのソースラベル TN を表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.getByText('TN')).toBeInTheDocument()
  })

  it('打者のソースラベル ALN を表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.getByText('ALN')).toBeInTheDocument()
  })

  // ── 信頼度 % の表示 ────────────────────────────────────────────────────────

  it('auto_filled (85%) の信頼度を表示する', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    // land_zone confidence_score=0.85 → 85%
    expect(screen.getByText('85%')).toBeInTheDocument()
  })

  it('suggested モードの ✓ ボタンが表示される', () => {
    const candidate = makeRallyCandidate({
      strokes: [
        {
          stroke_id: 101,
          stroke_num: 1,
          timestamp_sec: 1.0,
          land_zone: {
            value: 'NL',
            confidence_score: 0.55,
            source: 'tracknet',
            decision_mode: 'suggested',
            reason_codes: [],
          },
          hitter: null,
          front_back_role: null,
        },
      ],
    })
    const onAccept = vi.fn()
    render(
      <CVAssistPanel
        rallyCandidates={candidate}
        onAcceptLandZone={onAccept}
      />
    )
    // suggested の場合のみ ✓ ボタンが表示される
    const acceptButton = screen.getByText('✓')
    expect(acceptButton).toBeInTheDocument()
  })

  it('✓ ボタンをクリックすると onAcceptLandZone が呼ばれる', () => {
    const candidate = makeRallyCandidate({
      strokes: [
        {
          stroke_id: 101,
          stroke_num: 1,
          timestamp_sec: 1.0,
          land_zone: {
            value: 'NL',
            confidence_score: 0.55,
            source: 'tracknet',
            decision_mode: 'suggested',
            reason_codes: [],
          },
          hitter: null,
          front_back_role: null,
        },
      ],
    })
    const onAccept = vi.fn()
    render(
      <CVAssistPanel
        rallyCandidates={candidate}
        onAcceptLandZone={onAccept}
      />
    )
    fireEvent.click(screen.getByText('✓'))
    expect(onAccept).toHaveBeenCalledWith(1, 'NL')
  })

  it('auto_filled モードでは ✓ ボタンが表示されない', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.queryByText('✓')).not.toBeInTheDocument()
  })

  // ── 理由コード展開 ─────────────────────────────────────────────────────────

  it('track_present_high_confidence は理由コードとして表示されない', () => {
    // reason_codes に track_present_high_confidence があっても展開しない
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.queryByText(/高確信度トラック/)).not.toBeInTheDocument()
  })

  it('理由コードがあるとき展開トグルが表示される', () => {
    const candidate = makeRallyCandidate({
      strokes: [
        {
          stroke_id: 101,
          stroke_num: 1,
          timestamp_sec: 1.0,
          land_zone: {
            value: 'BL',
            confidence_score: 0.40,
            source: 'tracknet',
            decision_mode: 'review_required',
            reason_codes: ['landing_zone_ambiguous'],
          },
          hitter: null,
          front_back_role: null,
        },
      ],
    })
    render(<CVAssistPanel rallyCandidates={candidate} />)
    // ChevronRight ボタンが表示されること（title で確認）
    expect(screen.getByTitle('理由コードを表示')).toBeInTheDocument()
  })

  it('展開トグルをクリックすると理由ラベルが表示される', () => {
    const candidate = makeRallyCandidate({
      strokes: [
        {
          stroke_id: 101,
          stroke_num: 1,
          timestamp_sec: 1.0,
          land_zone: {
            value: 'BL',
            confidence_score: 0.40,
            source: 'tracknet',
            decision_mode: 'review_required',
            reason_codes: ['landing_zone_ambiguous'],
          },
          hitter: null,
          front_back_role: null,
        },
      ],
    })
    render(<CVAssistPanel rallyCandidates={candidate} />)
    fireEvent.click(screen.getByTitle('理由コードを表示'))
    expect(screen.getByText(/着地ゾーン不明確/)).toBeInTheDocument()
  })

  // ── 要確認理由（ラリーレベル） ────────────────────────────────────────────

  it('review_reason_codes がある場合「要確認理由」セクションを表示する', () => {
    const candidate = makeRallyCandidate({
      review_reason_codes: ['low_frame_coverage', 'hitter_undetected'],
    })
    render(<CVAssistPanel rallyCandidates={candidate} />)
    expect(screen.getByText('要確認理由')).toBeInTheDocument()
    expect(screen.getByText(/フレーム数不足/)).toBeInTheDocument()
    expect(screen.getByText(/打者検出不可/)).toBeInTheDocument()
  })

  it('review_reason_codes が空の場合「要確認理由」セクションは表示しない', () => {
    render(<CVAssistPanel rallyCandidates={makeRallyCandidate()} />)
    expect(screen.queryByText('要確認理由')).not.toBeInTheDocument()
  })

  // ── ダブルスロール ─────────────────────────────────────────────────────────

  it('front_back_role_signal がある場合ポジション推定を表示する', () => {
    const candidate = makeRallyCandidate({
      front_back_role_signal: {
        player_a_dominant: 'front',
        player_b_dominant: 'back',
        stability: 0.80,
      },
    })
    render(<CVAssistPanel rallyCandidates={candidate} />)
    expect(screen.getByText(/ポジション推定/)).toBeInTheDocument()
    expect(screen.getByText(/前衛/)).toBeInTheDocument()
    expect(screen.getByText(/後衛/)).toBeInTheDocument()
  })

  // ── ストロークなし ────────────────────────────────────────────────────────

  it('strokes が空のとき「ストローク候補がありません」を表示する', () => {
    const candidate = makeRallyCandidate({ strokes: [] })
    render(<CVAssistPanel rallyCandidates={candidate} />)
    expect(screen.getByText(/ストローク候補がありません/)).toBeInTheDocument()
  })

  // ── currentStrokeNum ──────────────────────────────────────────────────────

  it('currentStrokeNum と一致するストロークが強調される（ボーダークラス）', () => {
    render(
      <CVAssistPanel
        rallyCandidates={makeRallyCandidate()}
        currentStrokeNum={1}
      />
    )
    // stroke_num=1 の行がハイライト用クラスを持つ
    const rows = document.querySelectorAll('.border-blue-500\\/30')
    expect(rows.length).toBeGreaterThan(0)
  })
})
