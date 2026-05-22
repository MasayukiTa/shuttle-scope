/**
 * Pass 3: 各ストロークのショット種別 (詳細入力)
 * R48 step 7.
 *
 * 設計:
 *   - Pass 2 で作った "serve" / "__final_pending" の 2 stroke を起点に、
 *     ラリー内の中間ストロークを「タップ追加」で挿入していく。
 *   - 各 stroke に shot_type chip を割り当てる (smash / clear / drop /
 *     net / push / drive / lob / lift / cross / hairpin / serve / その他)
 *   - 最終的に rally.rally_length を stroke 総数で更新する。
 *
 * UX:
 *   - 既存 stroke を一覧表示 (左端 #1=serve, 右端=最後の決定打)
 *   - 中央に「+ストローク追加」エリア (現在 stroke 数 + 1 の位置)
 *   - 追加押下 → shot_type chip 選択 → AnnotateOverlay で hit_zone →
 *     land_zone → enqueue。player は前 stroke の opposite を既定にする
 *     (= ラリー中は交互打ち)。
 *   - 既存 stroke タップで shot_type だけ修正可。
 *
 * 注: shot_type 18 分類フル対応は backend / 既存 UI と整合する必要があるが
 *     スマホでは chip が多すぎると誤タップ多発する。よく使う 8 種に絞り、
 *     「その他」で詳細を後付け可能にする。
 */
import { useMemo, useState } from 'react'
import { AnnotateOverlay, ZoneCode } from './AnnotateOverlay'
import { enqueue } from '@/utils/mobileAnnotateQueue'
import { useTranslation } from 'react-i18next'

const COMMON_SHOTS = [
  { key: 'smash',    label: t('auto.Pass3ShotDetail.k1') },
  { key: 'clear',    label: t('auto.Pass3ShotDetail.k2') },
  { key: 'drop',     label: t('auto.Pass3ShotDetail.k3') },
  { key: 'net',      label: t('auto.Pass3ShotDetail.k4') },
  { key: 'push',     label: t('auto.Pass3ShotDetail.k5') },
  { key: 'drive',    label: t('auto.Pass3ShotDetail.k6') },
  { key: 'lift',     label: t('auto.Pass3ShotDetail.k7') },
  { key: 'cross',    label: t('auto.Pass3ShotDetail.k8') },
] as const

type ShotKey = typeof COMMON_SHOTS[number]['key']

interface StrokeLite {
  id?: number | null
  stroke_num: number
  player: 'player_a' | 'player_b'
  shot_type: string
  hit_zone?: string | null
  land_zone?: string | null
  pending?: boolean
}

interface Props {
  rally: {
    id: number
    rally_num: number
    set_num: number
    server: 'player_a' | 'player_b'
    winner: 'player_a' | 'player_b'
  }
  /** このラリーの既存 stroke (Pass 2 で作った serve + final、Pass 3 で増える分も) */
  strokes: StrokeLite[]
  onStrokeAdded: (s: StrokeLite) => void
  onStrokeUpdated: (s: StrokeLite) => void
  onClose: () => void
}

export function Pass3ShotDetail({
  rally,
  strokes,
  onStrokeAdded,
  onStrokeUpdated,
  onClose,
}: Props) {
  const sorted = useMemo(
    () => [...strokes].sort((a, b) => a.stroke_num - b.stroke_num),
    [strokes],
  )

  // 「追加モード」: shot 選択 → hit_zone → land_zone
  type AddState =
    | { phase: 'idle' }
    | { phase: 'pickShot' }
    | { phase: 'hitZone'; shot: ShotKey | 'other' }
    | { phase: 'landZone'; shot: ShotKey | 'other'; hit: ZoneCode }
  const [add, setAdd] = useState<AddState>({ phase: 'idle' })

  // shot_type 更新中の stroke (= 既存 chip タップ)
  const [editingStrokeNum, setEditingStrokeNum] = useState<number | null>(null)

  // Pass 2 が "final" を sentinel 9999 で挿入するので、その手前に詰める。
  // sentinel 以外の中で最大 stroke_num + 1 を採用。
  const intermediates = sorted.filter((s) => s.stroke_num < 9000)
  const finalSentinel = sorted.find((s) => s.stroke_num >= 9000) || null
  const nextStrokeNum = (intermediates[intermediates.length - 1]?.stroke_num ?? 0) + 1
  // 前 stroke の player の逆
  const nextPlayer: 'player_a' | 'player_b' = (() => {
    const prev = sorted[sorted.length - 1]
    if (!prev) return rally.server
    return prev.player === 'player_a' ? 'player_b' : 'player_a'
  })()

  const commitShot = async (shotKey: ShotKey | 'other', hit: ZoneCode, land: ZoneCode) => {
    const body = {
      stroke_num: nextStrokeNum,
      player: nextPlayer,
      shot_type: shotKey,
      hit_zone: hit,
      land_zone: land,
    }
    await enqueue('POST /api/strokes?rally_id=:rally_id', body, { rally_id: rally.id })
    onStrokeAdded({
      id: null,
      stroke_num: nextStrokeNum,
      player: nextPlayer,
      shot_type: shotKey,
      hit_zone: hit,
      land_zone: land,
      pending: true,
    })
    // rally.rally_length を「中間ストローク + 最終打 (sentinel が居れば +1)」に更新
    const newLength = nextStrokeNum + (finalSentinel ? 1 : 0)
    await enqueue('PUT /api/rallies/:id', { rally_length: newLength }, { id: rally.id })
    setAdd({ phase: 'idle' })
  }

  const editShot = async (strokeNum: number, shotKey: ShotKey | 'other') => {
    const s = strokes.find((x) => x.stroke_num === strokeNum)
    if (!s || !s.id) {
      setEditingStrokeNum(null)
      return
    }
    // PUT /api/strokes/:id は StrokeData full body を要求するため、現値で再送信
    await enqueue('PUT /api/strokes/:id', {
      stroke_num: s.stroke_num,
      player: s.player,
      shot_type: shotKey,
      hit_zone: s.hit_zone,
      land_zone: s.land_zone,
    }, { id: s.id })
    onStrokeUpdated({ ...s, shot_type: shotKey })
    setEditingStrokeNum(null)
  }

  // --- 追加 wizard 中の overlay 出し分け ---
  if (add.phase === 'hitZone') {
    return (
      <AnnotateOverlay
        prompt={`#${nextStrokeNum} (${add.shot}) — 打点を選択`}
        primaryLabel="次へ"
        onCommit={(z) => setAdd({ phase: 'landZone', shot: add.shot, hit: z })}
        onCancel={() => setAdd({ phase: 'idle' })}
      />
    )
  }
  if (add.phase === 'landZone') {
    return (
      <AnnotateOverlay
        prompt={`#${nextStrokeNum} (${add.shot}) — 着地点を選択`}
        primaryLabel="保存"
        onCommit={(z) => void commitShot(add.shot, add.hit, z)}
        onCancel={() => setAdd({ phase: 'idle' })}
      />
    )
  }
  if (add.phase === 'pickShot') {
    return (
      <ShotChipPicker
        title={`#${nextStrokeNum} のショット種別を選択 (${nextPlayer === 'player_a' ? 'A' : 'B'})`}
        onPick={(k) => setAdd({ phase: 'hitZone', shot: k })}
        onCancel={() => setAdd({ phase: 'idle' })}
      />
    )
  }
  if (editingStrokeNum != null) {
    return (
      <ShotChipPicker
        title={`#${editingStrokeNum} のショット種別を変更`}
        onPick={(k) => void editShot(editingStrokeNum, k)}
        onCancel={() => setEditingStrokeNum(null)}
      />
    )
  }

  // --- 一覧 + 追加ボタン ---
  return (
    <div className="absolute inset-0 bg-black/90 flex flex-col">
      <div className="bg-black/95 px-3 py-2 flex items-center gap-3 border-b border-gray-800 text-xs">
        <div className="text-yellow-200 font-bold">
          Pass 3 · ラリー {rally.rally_num} (set {rally.set_num})
        </div>
        <div className="flex-1" />
        <div className="text-gray-400">stroke {sorted.length} 件</div>
        <button
          type="button"
          onClick={onClose}
          className="px-2 py-1 rounded bg-gray-700 text-white text-[10px]"
        >
          閉じる
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {sorted.length === 0 && (
          <div className="text-gray-500 text-sm text-center py-4">
            Pass 2 でサーブと決定打を入れてから Pass 3 に来てください
          </div>
        )}
        {sorted.map((s) => (
          <button
            key={s.stroke_num}
            type="button"
            onClick={() => setEditingStrokeNum(s.stroke_num)}
            className="w-full flex items-center gap-3 px-3 py-2 rounded bg-gray-800 hover:bg-gray-700"
          >
            <span className="font-mono text-[11px] text-gray-400">#{s.stroke_num}</span>
            <span className={`text-xs font-bold ${
              s.player === 'player_a' ? 'text-blue-400' : 'text-pink-400'
            }`}>
              {s.player === 'player_a' ? 'A' : 'B'}
            </span>
            <span className="text-xs">
              {COMMON_SHOTS.find((c) => c.key === s.shot_type)?.label
                ?? (s.shot_type === '__final_pending' ? '(決定打: 未分類)'
                : s.shot_type === 'serve' ? 'サーブ'
                : s.shot_type)}
            </span>
            <div className="flex-1" />
            <span className="font-mono text-[10px] text-gray-500">
              {s.hit_zone ?? '-'} → {s.land_zone ?? '-'}
            </span>
            {s.pending && (
              <span className="text-[10px] text-amber-400">pending</span>
            )}
          </button>
        ))}

        {/* 追加ボタン */}
        <button
          type="button"
          onClick={() => setAdd({ phase: 'pickShot' })}
          className="w-full px-3 py-3 rounded-lg border-2 border-dashed border-gray-600 text-gray-300 text-sm hover:bg-gray-800"
        >
          + #{nextStrokeNum} のストロークを追加 ({nextPlayer === 'player_a' ? 'A' : 'B'})
        </button>
      </div>
    </div>
  )
}


function ShotChipPicker({
  title,
  onPick,
  onCancel,
}: {
  title: string
  onPick: (key: ShotKey | 'other') => void
  onCancel: () => void
}) {
  return (
    <div className="absolute inset-0 bg-black/95 flex flex-col">
      <div className="px-3 py-2 border-b border-gray-800 text-xs text-yellow-200 font-bold">
        {title}
      </div>
      <div className="flex-1 p-3 grid grid-cols-2 gap-2 content-start">
        {COMMON_SHOTS.map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={() => onPick(c.key)}
            className="px-3 py-3 rounded-lg bg-gray-800 hover:bg-gray-700 text-white text-sm font-medium"
            style={{ minHeight: '52px' }}
          >
            {c.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onPick('other')}
          className="col-span-2 px-3 py-2 rounded-lg bg-gray-700 text-gray-200 text-xs"
          style={{ minHeight: '44px' }}
        >
          その他 (後で詳細入力)
        </button>
      </div>
      <div className="px-3 py-2 border-t border-gray-800">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded bg-gray-700 text-white text-xs"
        >
          取消
        </button>
      </div>
    </div>
  )
}
