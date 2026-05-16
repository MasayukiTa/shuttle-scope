/**
 * Pass 1: ラリー区切り (得点が入った瞬間 = rally end timestamp)
 * R48 step 5.
 *
 * 動作:
 *   - 動画タップ → pause → このコンポーネント表示
 *   - 「A 得点」「B 得点」の 2 つの大ボタンだけ
 *   - タップで「直前のラリー終了 + 得点」として enqueue
 *   - サーブ権 / score は前ラリーから自動算出
 *
 * 認知負荷を下げるため:
 *   - 画面上に「現在の score」「セット番号」を常時表示
 *   - 入力するのは「A か B か」だけ
 *   - end_type / rally_length / ストローク詳細は Pass 2/3 で埋める
 *   - set rollover (21 点 + 2 点差) はバナーで通知のみ、自動切替はしない
 *     (誤判定を避けるため、Set 終了ボタンを明示タップで進める)
 */
import { useMemo, useState } from 'react'
// 規約: lucide-react は段階廃止。Material Symbols (MIcon) を使う。
import { MIcon } from '@/components/common/MIcon'
import { enqueue } from '@/utils/mobileAnnotateQueue'

interface RallyLite {
  id?: number | null
  client_uuid: string
  set_id: number
  rally_num: number
  server: 'player_a' | 'player_b'
  winner: 'player_a' | 'player_b'
  score_a_after: number
  score_b_after: number
  video_timestamp_end: number
  pending?: boolean
}

interface SetInfo {
  id: number
  set_num: number
}

interface Props {
  matchId: string | number
  currentSet: SetInfo
  /** 既存ラリー (最新が末尾) — サーバ取得済 + ローカル追加分の合算 */
  rallies: RallyLite[]
  /** 動画 pause 位置 (= rally end timestamp) */
  pausedAtSec: number
  /** ラリー追加時に親に通知 (UI 反映用) */
  onRallyAdded: (rally: RallyLite) => void
  /** 入力キャンセル (動画に戻る) */
  onCancel: () => void
  /** Undo: 直前のラリーを取消す */
  onUndoLast?: () => void
  /** 「セット終了 → 次のセット開始」ボタン押下時 */
  onSetEnded?: () => void
  /** CV 推奨ヒント (任意): pausedAtSec 付近の候補 stroke から計算した winner 候補。
      hint だけ表示、確定は user タップ。 */
  cvHint?: {
    suggestedWinner?: 'player_a' | 'player_b'
    confidence?: number
    mode?: string  // 'auto_filled' | 'suggested' | 'review_required'
  } | null
}

export function Pass1RallyEnd({
  matchId,
  currentSet,
  rallies,
  pausedAtSec,
  onRallyAdded,
  onCancel,
  onUndoLast,
  onSetEnded,
  cvHint,
}: Props) {
  const [busy, setBusy] = useState(false)

  // 現スコア計算: 同セット内の最新ラリーから (1-based set_num のラリーだけ集計)
  const { scoreA, scoreB, lastRally } = useMemo(() => {
    const setRallies = rallies.filter((r) => r.set_id === currentSet.id)
    if (setRallies.length === 0) {
      return { scoreA: 0, scoreB: 0, lastRally: null as RallyLite | null }
    }
    const last = setRallies[setRallies.length - 1]
    return {
      scoreA: last.score_a_after,
      scoreB: last.score_b_after,
      lastRally: last,
    }
  }, [rallies, currentSet.id])

  // サーブ権 (= 直前のラリーの winner、初回は player_a 既定)
  const nextServer: 'player_a' | 'player_b' = lastRally?.winner ?? 'player_a'

  // 21 点 + 2 点差なら set 終了候補
  const setEndingSoon = (() => {
    const max = Math.max(scoreA, scoreB)
    const diff = Math.abs(scoreA - scoreB)
    return (max >= 21 && diff >= 2) || max >= 30
  })()

  const submit = async (winner: 'player_a' | 'player_b') => {
    if (busy) return
    setBusy(true)
    try {
      const newA = scoreA + (winner === 'player_a' ? 1 : 0)
      const newB = scoreB + (winner === 'player_b' ? 1 : 0)
      const rallyNum = (lastRally?.rally_num ?? 0) + 1
      // backend RallyCreate schema (`extra='forbid'`) に合わせる:
      // score_a_before/b_before, annotation_mode は schema 非対応のため body に含めない
      // (DB model 側で default=0 / NULL に倒れる)。
      const body = {
        set_id: currentSet.id,
        rally_num: rallyNum,
        server: nextServer,
        winner,
        end_type: 'unknown',         // Pass 2/3 で更新
        rally_length: 0,             // Pass 3 で stroke 追加につれ更新
        score_a_after: newA,
        score_b_after: newB,
        video_timestamp_end: pausedAtSec,
        video_timestamp_start: lastRally?.video_timestamp_end ?? null,
        is_deuce: newA >= 20 && newB >= 20,
      }
      const { clientUuid } = await enqueue('POST /api/rallies', body)
      const local: RallyLite = {
        id: null,
        client_uuid: clientUuid,
        set_id: currentSet.id,
        rally_num: rallyNum,
        server: nextServer,
        winner,
        score_a_after: newA,
        score_b_after: newB,
        video_timestamp_end: pausedAtSec,
        pending: true,
      }
      onRallyAdded(local)
    } finally {
      setBusy(false)
    }
  }

  // 大ボタン: A 側は左, B 側は右
  return (
    <div className="absolute inset-0 bg-black/85 flex flex-col">
      {/* ヘッダ: セット番号 + score */}
      <div className="bg-black/90 px-3 py-2 flex items-center gap-3 border-b border-gray-800 text-xs">
        <div className="text-yellow-200 font-bold">
          Pass 1 — 得点が入った瞬間に A / B
        </div>
        <div className="flex-1" />
        <div className="text-gray-300">Set {currentSet.set_num}</div>
        <div className="font-mono text-lg text-white">
          <span className="text-blue-400">{scoreA}</span>
          <span className="mx-1 text-gray-500">-</span>
          <span className="text-pink-400">{scoreB}</span>
        </div>
        <div className="font-mono text-[10px] text-gray-500">
          @{pausedAtSec.toFixed(1)}s
        </div>
      </div>

      {/* set 終了候補バナー */}
      {setEndingSoon && (
        <div className="bg-amber-900/40 border-b border-amber-700/40 text-amber-200 text-xs px-3 py-1.5 text-center">
          このセットは終了している可能性があります。終わったら下の「セット終了」を押してください。
        </div>
      )}

      {/* 2 ボタン: CV 推奨側は左上に「CV 推奨」バッジ */}
      <div className="flex-1 flex">
        <button
          type="button"
          disabled={busy}
          onClick={() => submit('player_a')}
          className="flex-1 flex flex-col items-center justify-center gap-2 m-2 rounded-2xl bg-blue-700 active:bg-blue-600 disabled:opacity-50 border-2 border-blue-400 relative"
        >
          {cvHint?.suggestedWinner === 'player_a' && (
            <span
              className="absolute top-2 left-2 px-1.5 py-0.5 rounded text-[10px] font-mono"
              style={{ backgroundColor: 'rgba(245,158,11,0.95)', color: '#ffffff' }}
            >
              CV {cvHint.confidence ? `${Math.round(cvHint.confidence * 100)}%` : ''}
            </span>
          )}
          <div className="text-5xl font-bold text-white">A</div>
          <div className="text-xs text-blue-200">プレイヤーA 得点</div>
          <div className="text-[10px] text-blue-300/80">
            → {scoreA + 1} - {scoreB}
          </div>
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => submit('player_b')}
          className="flex-1 flex flex-col items-center justify-center gap-2 m-2 rounded-2xl bg-pink-700 active:bg-pink-600 disabled:opacity-50 border-2 border-pink-400 relative"
        >
          {cvHint?.suggestedWinner === 'player_b' && (
            <span
              className="absolute top-2 left-2 px-1.5 py-0.5 rounded text-[10px] font-mono"
              style={{ backgroundColor: 'rgba(245,158,11,0.95)', color: '#ffffff' }}
            >
              CV {cvHint.confidence ? `${Math.round(cvHint.confidence * 100)}%` : ''}
            </span>
          )}
          <div className="text-5xl font-bold text-white">B</div>
          <div className="text-xs text-pink-200">プレイヤーB 得点</div>
          <div className="text-[10px] text-pink-300/80">
            → {scoreA} - {scoreB + 1}
          </div>
        </button>
      </div>

      {/* 下部: Undo / Set終了 / 動画に戻る */}
      <div className="bg-black/90 px-3 py-2 flex items-center gap-2 border-t border-gray-800 text-xs">
        <button
          type="button"
          onClick={onUndoLast}
          disabled={!onUndoLast || !lastRally}
          className="px-3 py-2 rounded bg-gray-800 text-white disabled:opacity-30 flex items-center gap-1"
          title="直前のラリーを取消"
        >
          <MIcon name="undo" size={14} /> 直前取消
        </button>
        <button
          type="button"
          onClick={onSetEnded}
          disabled={!onSetEnded || !setEndingSoon}
          className="px-3 py-2 rounded bg-amber-700 text-white disabled:opacity-30"
        >
          セット終了
        </button>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-2 rounded bg-gray-700 text-white"
        >
          <span className="inline-flex items-center gap-1">
            <MIcon name="arrow_back" size={14} />
            動画に戻る
          </span>
        </button>
      </div>
    </div>
  )
}
