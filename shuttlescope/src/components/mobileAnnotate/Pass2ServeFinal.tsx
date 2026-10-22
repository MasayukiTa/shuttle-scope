/**
 * Pass 2: サーブ・最終打点 (4 step machine)
 * R48 step 6.
 *
 * 1 ラリーに対して 4 タップ:
 *   1) サーブ打点 (hit_zone)
 *   2) サーブ着地 (land_zone)
 *   3) 最終打点 (hit_zone)
 *   4) 最終着地 (land_zone)
 *
 * 完了で 2 つの Stroke を enqueue:
 *   - stroke_num=1, shot_type='serve', player=rally.server,
 *     hit_zone=serve_hit, land_zone=serve_land
 *   - stroke_num=9999, shot_type='__final_pending', player=最後に打った人,
 *     hit_zone=final_hit, land_zone=final_land
 *   最後に打った人は勝者とは限らない (相手のミスで終わるラリーは敗者が最後に打つ)。
 *   入力者が「決めた / 相手のミス」を選び、勝者から推定しない。
 *
 * サーブ 1 打でラリーが終わる場合 (サービスエース等) は、サーブ着地の入力後に
 * 「サーブで終了」を選ぶと serve 1 件 + rally_length=1 だけを保存する (最終打は別 stroke にしない)。
 *
 * Pass 3 が後で intermediate stroke を挿入する際に stroke_num を再採番する。
 *
 * UI:
 *   - 上部: 「ラリー N · サーブ打点」など現在 step を表示
 *   - メイン: AnnotateOverlay を 4 回連続で使う
 *   - 進捗ドット ● ● ○ ○ (左から)
 *   - キャンセル: その段階の入力だけ破棄 (累積した step は維持)、または
 *     最初に戻る選択肢
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnnotateOverlay, ZoneCode } from './AnnotateOverlay'
import { enqueue } from '@/utils/mobileAnnotateQueue'
import { finalHitterFor, type FinalShotOutcome } from '@/utils/mobileAnnotateRallies'
import { serveOnlyRallyPayload } from '@/utils/mobileAnnotatePass2'
import { resolveHitter, slotsOfTeam, type HitterSlot } from '@/utils/mobileAnnotateDoubles'

type Step = 'serve_hit' | 'serve_land' | 'final_hit' | 'final_land'
const STEP_ORDER: Step[] = ['serve_hit', 'serve_land', 'final_hit', 'final_land']

interface RallyTarget {
  id: number
  rally_num: number
  set_num: number
  server: 'player_a' | 'player_b'
  winner: 'player_a' | 'player_b'
}

interface Props {
  rally: RallyTarget
  /** ダブルス: サーバ・最終打者を個人 slot (partner を含む) で選ばせて保存する */
  doubles?: boolean
  onCompleted: () => void
  onCancel: () => void
}

export function Pass2ServeFinal({ rally, doubles = false, onCompleted, onCancel }: Props) {
  const { t } = useTranslation()
  const [serveSlot, setServeSlot] = useState<HitterSlot | null>(null)
  const [finalSlot, setFinalSlot] = useState<HitterSlot | null>(null)
  const [needSlot, setNeedSlot] = useState(false)
  const [stepIdx, setStepIdx] = useState(0)
  const [zones, setZones] = useState<Partial<Record<Step, ZoneCode>>>({})
  const [submitting, setSubmitting] = useState(false)
  const [outcome, setOutcome] = useState<FinalShotOutcome | null>(null)
  const [needOutcome, setNeedOutcome] = useState(false)
  const step = STEP_ORDER[stepIdx]
  // 各 step のプロンプト文。t() はコンポーネント内のみで参照する規約。
  const STEP_PROMPT = useMemo<Record<Step, string>>(() => ({
    serve_hit: t('auto.Pass2ServeFinal.prompt_serve_hit'),
    serve_land: t('auto.Pass2ServeFinal.prompt_serve_land'),
    final_hit: t('auto.Pass2ServeFinal.prompt_final_hit'),
    final_land: t('auto.Pass2ServeFinal.prompt_final_land'),
  }), [t])

  // 保存する打球者 (ダブルスは選択必須)。最終打者のチームは「決めた/相手のミス」で決まる。
  const finalTeam = outcome ? finalHitterFor(rally, outcome) : null
  const serveHitter = resolveHitter(doubles, rally.server, serveSlot)
  const finalHitter = finalTeam ? resolveHitter(doubles, finalTeam, finalSlot) : null

  const handleCommit = async (zone: ZoneCode) => {
    // 最終打の入力に進む前に、ラリーの終わり方を選んでもらう (勝者から推定しない)
    if (stepIdx >= 2 && !outcome) {
      setNeedOutcome(true)
      return
    }
    // ダブルスは実際の打球者 (主選手/パートナー) を選ばせる。A/B に潰すと誤帰属する。
    if (stepIdx < 2 && !serveHitter) {
      setNeedSlot(true)
      return
    }
    if (stepIdx >= 2 && !finalHitter) {
      setNeedSlot(true)
      return
    }
    setNeedSlot(false)
    const next = { ...zones, [step]: zone }
    setZones(next)
    if (stepIdx < STEP_ORDER.length - 1) {
      setStepIdx(stepIdx + 1)
      return
    }
    // 4 step 全部揃った → 2 stroke を enqueue
    setSubmitting(true)
    try {
      // backend POST /api/strokes は rally_id を QUERY PARAM で受ける。
      // body には StrokeData (extra='forbid') のフィールドのみ。
      // 「最終打点」は 9999 番で確保し、Pass 3 で間に挿入された際に
      // renumber する余地を持たせる。
      await enqueue('POST /api/strokes?rally_id=:rally_id', {
        stroke_num: 1,
        player: serveHitter as HitterSlot,
        shot_type: 'serve',
        hit_zone: next.serve_hit,
        land_zone: next.serve_land,
        // 人が画面で指定した入力 (未指定だと分析側の由来集計で全て unknown になる)
        source_method: 'manual',
        hit_zone_source: 'manual',
      }, { rally_id: rally.id })
      await enqueue('POST /api/strokes?rally_id=:rally_id', {
        stroke_num: 9999,            // sentinel: 最後尾
        // outcome は final_hit の確定時に必須にしてあるので、ここで未選択にはならない
        player: finalHitter as HitterSlot,
        shot_type: '__final_pending', // Pass 3 で更新
        hit_zone: next.final_hit,
        land_zone: next.final_land,
        source_method: 'manual',
        hit_zone_source: 'manual',
      }, { rally_id: rally.id })
      onCompleted()
    } finally {
      setSubmitting(false)
    }
  }

  // サーブ 1 打でラリーが終わる場合 (サービスエース等): 最終打はサーブ自身。
  // 別 stroke を作らず serve 1 件 + rally_length=1 だけを保存する。
  const handleServeOnly = async () => {
    if (submitting || !zones.serve_hit || !zones.serve_land) return
    if (!serveHitter) {
      setNeedSlot(true)
      return
    }
    setSubmitting(true)
    try {
      const { stroke, rallyLength } = serveOnlyRallyPayload(rally, zones, serveHitter)
      await enqueue('POST /api/strokes?rally_id=:rally_id', stroke, { rally_id: rally.id })
      await enqueue('PUT /api/rallies/:id', { rally_length: rallyLength }, { id: rally.id })
      onCompleted()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="absolute inset-0 bg-black/80 flex flex-col">
      {/* 上部: 進捗ドット + step 名 */}
      <div className="bg-black/90 px-3 py-2 flex items-center gap-3 border-b border-gray-800 text-xs">
        <div className="text-yellow-200 font-bold">
          {t('auto.Pass2ServeFinal.header', { n: rally.rally_num, m: rally.set_num })}
        </div>
        <div className="flex-1" />
        <div className="flex gap-1">
          {STEP_ORDER.map((s, i) => (
            <span
              key={s}
              className={`w-2.5 h-2.5 rounded-full ${
                i < stepIdx
                  ? 'bg-green-500'
                  : i === stepIdx
                  ? 'bg-yellow-300 animate-pulse-slow'
                  : 'bg-gray-700'
              }`}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={onCancel}
          className="px-2 py-1 rounded bg-gray-700 text-white text-[10px]"
        >
          {t('auto.Pass2ServeFinal.save_and_back')}
        </button>
      </div>

      {doubles && (stepIdx < 2 || finalTeam) && (
        <div
          className="bg-black/90 px-3 py-1.5 flex items-center gap-2 border-b border-gray-800 text-xs text-white"
          role="radiogroup"
          aria-label={stepIdx < 2 ? t('auto.Pass2ServeFinal.slot_serve_label') : t('auto.Pass2ServeFinal.slot_final_label')}
        >
          <span className={needSlot ? 'text-red-300 font-bold' : ''}>
            {stepIdx < 2 ? t('auto.Pass2ServeFinal.slot_serve_label') : t('auto.Pass2ServeFinal.slot_final_label')}
          </span>
          {slotsOfTeam(stepIdx < 2 ? rally.server : (finalTeam as 'player_a' | 'player_b')).map((slot) => {
            const current = stepIdx < 2 ? serveHitter : finalHitter
            return (
              <button
                key={slot}
                type="button"
                role="radio"
                aria-checked={current === slot}
                onClick={() => {
                  if (stepIdx < 2) setServeSlot(slot)
                  else setFinalSlot(slot)
                  setNeedSlot(false)
                }}
                className={`px-2 py-1 rounded ${current === slot ? 'bg-green-700' : 'bg-gray-700'}`}
              >
                {t(`auto.HitterSlot.${slot}`)}
              </button>
            )
          })}
        </div>
      )}

      {stepIdx >= 2 && (
        <div className="bg-black/90 px-3 py-1.5 flex items-center gap-2 border-b border-gray-800 text-xs text-white">
          <span className={needOutcome && !outcome ? 'text-red-300 font-bold' : ''}>
            {t('auto.Pass2ServeFinal.outcome_label')}
          </span>
          <button
            type="button"
            onClick={() => setOutcome('winner_shot')}
            aria-pressed={outcome === 'winner_shot'}
            className={`px-2 py-1 rounded ${outcome === 'winner_shot' ? 'bg-green-700' : 'bg-gray-700'}`}
          >
            {t('auto.Pass2ServeFinal.outcome_winner_shot')}
          </button>
          <button
            type="button"
            onClick={() => setOutcome('opponent_error')}
            aria-pressed={outcome === 'opponent_error'}
            className={`px-2 py-1 rounded ${outcome === 'opponent_error' ? 'bg-green-700' : 'bg-gray-700'}`}
          >
            {t('auto.Pass2ServeFinal.outcome_opponent_error')}
          </button>
          <div className="flex-1" />
          <button
            type="button"
            disabled={submitting}
            onClick={() => void handleServeOnly()}
            className="px-2 py-1 rounded bg-gray-700 disabled:opacity-40"
          >
            {t('auto.Pass2ServeFinal.serve_only')}
          </button>
        </div>
      )}

      <div className="relative flex-1" data-tutorial="mobileAnnotate.zonePicker">
        <AnnotateOverlay
          prompt={STEP_PROMPT[step]}
          primaryLabel={stepIdx === STEP_ORDER.length - 1 ? t('auto.Pass2ServeFinal.primary_submit') : t('auto.Pass2ServeFinal.primary_next')}
          cancelLabel={t('auto.Pass2ServeFinal.cancel_retry')}
          onCommit={(z) => {
            if (submitting) return
            void handleCommit(z)
          }}
          onCancel={() => {
            // 現 step だけリセット (これまでの zone は保持)
            const reset = { ...zones }
            delete reset[step]
            setZones(reset)
          }}
        />
        {submitting && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-yellow-200 text-sm">
            {t('auto.Pass2ServeFinal.saving')}
          </div>
        )}
      </div>
    </div>
  )
}
