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
 *   - stroke_num=2, shot_type='__final_pending', player=rally.winner,
 *     hit_zone=final_hit, land_zone=final_land
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
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AnnotateOverlay, ZoneCode } from './AnnotateOverlay'
import { enqueue } from '@/utils/mobileAnnotateQueue'

type Step = 'serve_hit' | 'serve_land' | 'final_hit' | 'final_land'
const STEP_ORDER: Step[] = ['serve_hit', 'serve_land', 'final_hit', 'final_land']
const STEP_PROMPT: Record<Step, string> = {
  serve_hit: 'サーブ打点を選択',
  serve_land: 'サーブ着地を選択',
  final_hit: '決まった一打の打点を選択',
  final_land: '決まった一打の着地を選択',
}

interface RallyTarget {
  id: number
  rally_num: number
  set_num: number
  server: 'player_a' | 'player_b'
  winner: 'player_a' | 'player_b'
}

interface Props {
  rally: RallyTarget
  onCompleted: () => void
  onCancel: () => void
}

export function Pass2ServeFinal({ rally, onCompleted, onCancel }: Props) {
  const { t } = useTranslation()
  const [stepIdx, setStepIdx] = useState(0)
  const [zones, setZones] = useState<Partial<Record<Step, ZoneCode>>>({})
  const [submitting, setSubmitting] = useState(false)
  const step = STEP_ORDER[stepIdx]

  const handleCommit = async (zone: ZoneCode) => {
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
        player: rally.server,
        shot_type: 'serve',
        hit_zone: next.serve_hit,
        land_zone: next.serve_land,
      }, { rally_id: rally.id })
      await enqueue('POST /api/strokes?rally_id=:rally_id', {
        stroke_num: 9999,            // sentinel: 最後尾
        player: rally.winner,
        shot_type: '__final_pending', // Pass 3 で更新
        hit_zone: next.final_hit,
        land_zone: next.final_land,
      }, { rally_id: rally.id })
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

      <div className="relative flex-1" data-tutorial="mobileAnnotate.zonePicker">
        <AnnotateOverlay
          prompt={STEP_PROMPT[step]}
          primaryLabel={stepIdx === STEP_ORDER.length - 1 ? '送信' : '次へ'}
          cancelLabel="やり直す"
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
