/**
 * CVAssistPanel — ラリーごとの CV 補助アノテーション候補パネル
 *
 * 表示内容:
 *   - 現在ラリーの CV 候補（着地ゾーン / 打者 / ダブルスロール）
 *   - 信頼度バッジ（自動入力 / 候補 / 要確認）
 *   - ワンタップ承認ボタン（suggested → confirmed）
 *   - 要確認フラグ・理由表示
 */
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { CheckCircle, AlertTriangle, Info, Zap } from 'lucide-react'
import type { RallyCVCandidate, StrokeCVCandidate } from '@/types/cv'
import { CVCandidateBadge } from './CVCandidateBadge'

interface Props {
  rallyCandidates: RallyCVCandidate | null
  /** 現在のストローク番号（ハイライト用） */
  currentStrokeNum?: number
  /** 着地ゾーン候補を承認するコールバック */
  onAcceptLandZone?: (strokeNum: number, zone: string) => void
  /** 打者候補を承認するコールバック */
  onAcceptHitter?: (strokeNum: number, player: string) => void
  className?: string
}

// 理由コードの日本語ラベル
const REASON_LABELS: Record<string, string> = {
  low_frame_coverage:      'フレーム数不足',
  alignment_missing:       'アライメントデータなし',
  landing_zone_ambiguous:  '着地ゾーン不明確',
  hitter_undetected:       '打者検出不可',
  multiple_near_players:   '複数の近傍プレイヤー',
  role_state_unstable:     'ロール状態不安定',
  track_present_high_confidence: '高確信度トラック',
}

function reasonLabel(code: string): string {
  return REASON_LABELS[code] ?? code
}

function StrokeRow({
  sc,
  isCurrent,
  onAcceptLandZone,
  onAcceptHitter,
}: {
  sc: StrokeCVCandidate
  isCurrent: boolean
  onAcceptLandZone?: (strokeNum: number, zone: string) => void
  onAcceptHitter?: (strokeNum: number, player: string) => void
}) {
  const { t } = useTranslation()
  const hasAny = sc.land_zone || sc.hitter

  return (
    <div
      className={clsx(
        'rounded px-2 py-1.5 text-xs transition-colors',
        isCurrent
          ? 'bg-blue-500/10 border border-blue-500/30'
          : 'border border-transparent hover:bg-white/5',
      )}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className="font-semibold text-[11px] text-slate-300 w-5 shrink-0">
          #{sc.stroke_num}
        </span>
        {!hasAny && (
          <span className="text-slate-500 text-[10px]">候補なし</span>
        )}

        {/* 着地ゾーン */}
        {sc.land_zone && (
          <div className="flex items-center gap-1 min-w-0">
            <span className="text-slate-400 text-[10px] shrink-0">着地</span>
            <span className="font-mono font-bold text-white text-[11px]">
              {sc.land_zone.value}
            </span>
            <CVCandidateBadge mode={sc.land_zone.decision_mode} compact />
            {sc.land_zone.decision_mode === 'suggested' && onAcceptLandZone && (
              <button
                onClick={() => onAcceptLandZone(sc.stroke_num, sc.land_zone!.value)}
                className="ml-0.5 text-[9px] px-1 py-0.5 rounded bg-blue-500/30 hover:bg-blue-500/50 text-blue-200 transition-colors"
                title="この着地ゾーンを承認"
              >
                ✓
              </button>
            )}
          </div>
        )}

        {/* 打者 */}
        {sc.hitter && (
          <div className="flex items-center gap-1 min-w-0 ml-1">
            <span className="text-slate-400 text-[10px] shrink-0">打者</span>
            <span className="font-bold text-white text-[11px]">
              {sc.hitter.value === 'player_a'
                ? t('annotator.player_a_label', 'A')
                : t('annotator.player_b_label', 'B')}
            </span>
            <CVCandidateBadge mode={sc.hitter.decision_mode} compact />
            {sc.hitter.decision_mode === 'suggested' && onAcceptHitter && (
              <button
                onClick={() => onAcceptHitter(sc.stroke_num, sc.hitter!.value)}
                className="ml-0.5 text-[9px] px-1 py-0.5 rounded bg-blue-500/30 hover:bg-blue-500/50 text-blue-200 transition-colors"
                title="この打者候補を承認"
              >
                ✓
              </button>
            )}
          </div>
        )}
      </div>

      {/* ダブルスロール */}
      {sc.front_back_role && (sc.front_back_role.player_a !== 'unclear' || sc.front_back_role.player_b !== 'unclear') && (
        <div className="text-[9px] text-slate-500 ml-5 mt-0.5">
          A:{sc.front_back_role.player_a === 'front' ? '前' : sc.front_back_role.player_a === 'back' ? '後' : '?'}
          {' / '}
          B:{sc.front_back_role.player_b === 'front' ? '前' : sc.front_back_role.player_b === 'back' ? '後' : '?'}
        </div>
      )}
    </div>
  )
}

export function CVAssistPanel({
  rallyCandidates,
  currentStrokeNum,
  onAcceptLandZone,
  onAcceptHitter,
  className,
}: Props) {
  if (!rallyCandidates) {
    return (
      <div className={clsx('text-slate-500 text-xs text-center py-3', className)}>
        <Info size={14} className="inline mr-1 opacity-50" />
        CV 候補なし
      </div>
    )
  }

  const summary = rallyCandidates.cv_confidence_summary
  const hasReview = rallyCandidates.review_reason_codes.length > 0
  const hasStrokes = rallyCandidates.strokes.length > 0

  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      {/* ─ サマリーバー ─ */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1 text-[10px] text-slate-400">
          <Zap size={11} className="text-emerald-400" />
          着地ゾーン
          <span className="font-semibold text-white ml-0.5">
            {Math.round(summary.land_zone_fill_rate * 100)}%
          </span>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-slate-400">
          <Zap size={11} className="text-blue-400" />
          打者
          <span className="font-semibold text-white ml-0.5">
            {Math.round(summary.hitter_fill_rate * 100)}%
          </span>
        </div>
        {summary.avg_confidence > 0 && (
          <div className="text-[10px] text-slate-500 ml-auto">
            平均信頼度 {Math.round(summary.avg_confidence * 100)}%
          </div>
        )}
      </div>

      {/* ─ ダブルスロールシグナル ─ */}
      {rallyCandidates.front_back_role_signal && (
        <div className="text-[10px] text-slate-400 bg-white/5 rounded px-2 py-1 flex items-center gap-2">
          <span className="text-slate-500">ポジション</span>
          <span>
            A:{rallyCandidates.front_back_role_signal.player_a_dominant === 'front' ? '前衛' :
               rallyCandidates.front_back_role_signal.player_a_dominant === 'back'  ? '後衛' : '混合'}
          </span>
          <span>
            B:{rallyCandidates.front_back_role_signal.player_b_dominant === 'front' ? '前衛' :
               rallyCandidates.front_back_role_signal.player_b_dominant === 'back'  ? '後衛' : '混合'}
          </span>
          <span className="ml-auto text-slate-500">
            安定度 {Math.round(rallyCandidates.front_back_role_signal.stability * 100)}%
          </span>
        </div>
      )}

      {/* ─ 要確認理由 ─ */}
      {hasReview && (
        <div className="flex items-start gap-1.5 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1">
          <AlertTriangle size={11} className="text-amber-400 mt-0.5 shrink-0" />
          <div className="text-[10px] text-amber-300 flex flex-wrap gap-x-2 gap-y-0.5">
            {rallyCandidates.review_reason_codes.map((code) => (
              <span key={code}>{reasonLabel(code)}</span>
            ))}
          </div>
        </div>
      )}

      {/* ─ ストロークごとの候補 ─ */}
      {hasStrokes && (
        <div className="flex flex-col gap-0.5 max-h-48 overflow-y-auto">
          {rallyCandidates.strokes.map((sc) => (
            <StrokeRow
              key={sc.stroke_num}
              sc={sc}
              isCurrent={sc.stroke_num === currentStrokeNum}
              onAcceptLandZone={onAcceptLandZone}
              onAcceptHitter={onAcceptHitter}
            />
          ))}
        </div>
      )}

      {!hasStrokes && (
        <div className="text-slate-500 text-[10px] text-center py-1">
          このラリーにストローク候補がありません
        </div>
      )}
    </div>
  )
}
