/**
 * CVAssistPanel — ラリーごとの CV 補助アノテーション候補パネル
 *
 * 表示内容:
 *   - 現在ラリーの CV 候補（着地ゾーン / 打者 / ダブルスロール）
 *   - 信頼度 % + ソース + decision_mode バッジ（フィールドごとに明示）
 *   - ストロークごとの reason_codes（展開可能）
 *   - ワンタップ承認ボタン（suggested → confirmed）
 *   - 要確認フラグ・理由表示（ラリーレベル）
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { AlertTriangle, Info, Zap, ChevronDown, ChevronRight } from 'lucide-react'
import type { RallyCVCandidate, StrokeCVCandidate, CVFieldResult, CVSource } from '@/types/cv'
import { CVCandidateBadge } from './CVCandidateBadge'

interface Props {
  rallyCandidates: RallyCVCandidate | null
  currentStrokeNum?: number
  onAcceptLandZone?: (strokeNum: number, zone: string) => void
  onAcceptHitter?: (strokeNum: number, player: string) => void
  className?: string
}

// ── ラベル定義 ─────────────────────────────────────────────────────────────────

const REASON_LABELS: Record<string, string> = {
  low_frame_coverage:           'フレーム数不足',
  alignment_missing:            'アライメントデータなし',
  landing_zone_ambiguous:       '着地ゾーン不明確',
  hitter_undetected:            '打者検出不可',
  multiple_near_players:        '打者候補競合',
  role_state_unstable:          'ロール状態不安定',
  track_present_high_confidence:'高確信度トラック',
}

const SOURCE_LABELS: Record<CVSource, string> = {
  tracknet:  'TN',
  yolo:      'YOLO',
  alignment: 'ALN',
  fusion:    'FUS',
}

const SOURCE_TITLES: Record<CVSource, string> = {
  tracknet:  'TrackNet シャトル軌跡',
  yolo:      'YOLO プレイヤー検出',
  alignment: 'YOLO+TrackNet アライメント',
  fusion:    'YOLO+TrackNet 融合推定',
}

function reasonLabel(code: string): string {
  return REASON_LABELS[code] ?? code
}

// ── CVFieldChip: 単一フィールドの値・信頼度・ソース・バッジ ───────────────────

function CVFieldChip({
  label,
  field,
  onAccept,
  acceptTitle,
}: {
  label: string
  field: CVFieldResult
  onAccept?: () => void
  acceptTitle?: string
}) {
  const confPct = Math.round(field.confidence_score * 100)
  const srcLabel = SOURCE_LABELS[field.source as CVSource] ?? field.source
  const srcTitle = SOURCE_TITLES[field.source as CVSource] ?? field.source

  return (
    <div className="flex items-center gap-1 flex-wrap">
      <span className="text-slate-500 text-[10px] shrink-0 w-8">{label}</span>
      <span className="font-mono font-bold text-white text-[11px]">{field.value}</span>
      <CVCandidateBadge mode={field.decision_mode} compact />
      {/* 信頼度 */}
      <span
        className={clsx(
          'text-[9px] font-mono tabular-nums',
          confPct >= 72 ? 'text-emerald-400' : confPct >= 48 ? 'text-blue-400' : 'text-amber-400'
        )}
        title={`信頼度スコア: ${field.confidence_score.toFixed(3)}`}
      >
        {confPct}%
      </span>
      {/* ソース */}
      <span
        className="text-[9px] text-slate-600 bg-slate-700/50 rounded px-0.5"
        title={srcTitle}
      >
        {srcLabel}
      </span>
      {/* ✓ 承認ボタン (suggested のみ) */}
      {field.decision_mode === 'suggested' && onAccept && (
        <button
          onClick={onAccept}
          className="text-[9px] px-1 py-0.5 rounded bg-blue-500/30 hover:bg-blue-500/50 text-blue-200 transition-colors"
          title={acceptTitle ?? '承認'}
        >
          ✓
        </button>
      )}
    </div>
  )
}

// ── StrokeRow: ストロークごとの候補行 ────────────────────────────────────────

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
  const [expanded, setExpanded] = useState(false)

  const hasAny = sc.land_zone || sc.hitter
  const allReasonCodes = [
    ...(sc.land_zone?.reason_codes ?? []),
    ...(sc.hitter?.reason_codes ?? []),
  ].filter((c) => c !== 'track_present_high_confidence') // 高確信度コードは表示しない（ノイズ）

  // ユニーク理由コードのみ表示
  const uniqueReasons = [...new Set(allReasonCodes)]

  return (
    <div
      className={clsx(
        'rounded px-2 py-1.5 text-xs transition-colors',
        isCurrent
          ? 'bg-blue-500/10 border border-blue-500/30'
          : 'border border-transparent hover:bg-white/5',
      )}
    >
      <div className="flex items-start gap-1.5">
        {/* ストローク番号 */}
        <span className="font-semibold text-[11px] text-slate-300 w-5 shrink-0 mt-0.5">
          #{sc.stroke_num}
        </span>

        <div className="flex flex-col gap-0.5 flex-1 min-w-0">
          {!hasAny && (
            <span className="text-slate-500 text-[10px]">候補なし</span>
          )}

          {/* 着地ゾーン */}
          {sc.land_zone && (
            <CVFieldChip
              label="着地"
              field={sc.land_zone}
              onAccept={onAcceptLandZone ? () => onAcceptLandZone(sc.stroke_num, sc.land_zone!.value) : undefined}
              acceptTitle="この着地ゾーンを承認"
            />
          )}

          {/* 打者 */}
          {sc.hitter && (
            <CVFieldChip
              label="打者"
              field={{
                ...sc.hitter,
                value: sc.hitter.value === 'player_a'
                  ? t('annotator.player_a_label', 'A')
                  : t('annotator.player_b_label', 'B'),
              }}
              onAccept={onAcceptHitter ? () => onAcceptHitter(sc.stroke_num, sc.hitter!.value) : undefined}
              acceptTitle="この打者候補を承認"
            />
          )}

          {/* ダブルスロール */}
          {sc.front_back_role && (sc.front_back_role.player_a !== 'unclear' || sc.front_back_role.player_b !== 'unclear') && (
            <div className="text-[9px] text-slate-500 flex items-center gap-1 mt-0.5">
              <span>ポジション</span>
              <span>A:{sc.front_back_role.player_a === 'front' ? '前' : sc.front_back_role.player_a === 'back' ? '後' : '?'}</span>
              <span>B:{sc.front_back_role.player_b === 'front' ? '前' : sc.front_back_role.player_b === 'back' ? '後' : '?'}</span>
              <span className="text-slate-600">
                ({Math.round(sc.front_back_role.confidence * 100)}%)
              </span>
            </div>
          )}
        </div>

        {/* 理由コード展開トグル */}
        {uniqueReasons.length > 0 && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-amber-400/70 hover:text-amber-400 shrink-0 mt-0.5"
            title="理由コードを表示"
          >
            {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          </button>
        )}
      </div>

      {/* 理由コード詳細（展開時） */}
      {expanded && uniqueReasons.length > 0 && (
        <div className="ml-6 mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5">
          {uniqueReasons.map((code) => (
            <span key={code} className="text-[9px] text-amber-400/70">
              · {reasonLabel(code)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── メインコンポーネント ───────────────────────────────────────────────────────

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

  // 理由コードをカテゴリ別に分類
  const dataAvailabilityReasons = rallyCandidates.review_reason_codes.filter(c =>
    ['low_frame_coverage', 'alignment_missing'].includes(c)
  )
  const qualityReasons = rallyCandidates.review_reason_codes.filter(c =>
    ['landing_zone_ambiguous', 'hitter_undetected', 'multiple_near_players', 'role_state_unstable'].includes(c)
  )

  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      {/* ─ サマリーバー ─ */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1 text-[10px] text-slate-400">
          <Zap size={11} className="text-emerald-400" />
          <span>着地ゾーン</span>
          <span className={clsx(
            'font-semibold ml-0.5',
            summary.land_zone_fill_rate >= 0.7 ? 'text-emerald-300' :
            summary.land_zone_fill_rate >= 0.4 ? 'text-blue-300' : 'text-amber-300'
          )}>
            {Math.round(summary.land_zone_fill_rate * 100)}%
          </span>
        </div>
        <div className="flex items-center gap-1 text-[10px] text-slate-400">
          <Zap size={11} className="text-blue-400" />
          <span>打者</span>
          <span className={clsx(
            'font-semibold ml-0.5',
            summary.hitter_fill_rate >= 0.7 ? 'text-emerald-300' :
            summary.hitter_fill_rate >= 0.4 ? 'text-blue-300' : 'text-amber-300'
          )}>
            {Math.round(summary.hitter_fill_rate * 100)}%
          </span>
        </div>
        {summary.avg_confidence > 0 && (
          <div className="text-[10px] text-slate-500 ml-auto tabular-nums">
            平均信頼度 {Math.round(summary.avg_confidence * 100)}%
          </div>
        )}
      </div>

      {/* ─ ダブルスロールシグナル ─ */}
      {rallyCandidates.front_back_role_signal && (
        <div className="text-[10px] text-slate-400 bg-white/5 rounded px-2 py-1 flex items-center gap-2 flex-wrap">
          <span className="text-slate-500 shrink-0">ポジション推定</span>
          <span>
            A:
            <span className="font-semibold ml-0.5">
              {rallyCandidates.front_back_role_signal.player_a_dominant === 'front' ? '前衛' :
               rallyCandidates.front_back_role_signal.player_a_dominant === 'back'  ? '後衛' : '混合'}
            </span>
          </span>
          <span>
            B:
            <span className="font-semibold ml-0.5">
              {rallyCandidates.front_back_role_signal.player_b_dominant === 'front' ? '前衛' :
               rallyCandidates.front_back_role_signal.player_b_dominant === 'back'  ? '後衛' : '混合'}
            </span>
          </span>
          <span className={clsx(
            'ml-auto text-[9px] tabular-nums',
            rallyCandidates.front_back_role_signal.stability >= 0.65 ? 'text-emerald-400/70' : 'text-amber-400/70'
          )}>
            安定度 {Math.round(rallyCandidates.front_back_role_signal.stability * 100)}%
          </span>
        </div>
      )}

      {/* ─ 要確認理由（カテゴリ別） ─ */}
      {hasReview && (
        <div className="flex flex-col gap-0.5 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1">
          <div className="flex items-center gap-1 mb-0.5">
            <AlertTriangle size={10} className="text-amber-400 shrink-0" />
            <span className="text-[9px] text-amber-400 font-semibold">要確認理由</span>
          </div>
          {dataAvailabilityReasons.length > 0 && (
            <div className="text-[9px] text-amber-300/80">
              <span className="text-slate-500 mr-1">データ:</span>
              {dataAvailabilityReasons.map(reasonLabel).join(' · ')}
            </div>
          )}
          {qualityReasons.length > 0 && (
            <div className="text-[9px] text-amber-300/80">
              <span className="text-slate-500 mr-1">品質:</span>
              {qualityReasons.map(reasonLabel).join(' · ')}
            </div>
          )}
        </div>
      )}

      {/* ─ ストロークごとの候補 ─ */}
      {hasStrokes ? (
        <div className="flex flex-col gap-0.5 max-h-52 overflow-y-auto pr-0.5">
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
      ) : (
        <div className="text-slate-500 text-[10px] text-center py-1">
          このラリーにストローク候補がありません
        </div>
      )}
    </div>
  )
}
