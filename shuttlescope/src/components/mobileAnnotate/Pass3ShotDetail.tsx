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
 *   - 既存 stroke タップで 球種 → 打点 → 着地点 を既存値入りで修正可
 *     (球種だけ・ゾーンだけの変更は、該当ステップで既存値のまま確定する)。
 *
 * 注: 保存は backend の canonical ShotType 値で行う。スマホでは chip が多すぎると
 *     誤タップ多発するため、よく使う 8 種を上部に固定表示し、残りは「その他」
 *     折り畳みで展開表示する。誤タップ回避のためタッチターゲットは 44px 以上を維持。
 *
 *   - 固定 8 種: smash / clear / drop / net / push / drive / lift / cross
 *     (既存の保存値をそのまま踏襲。ラベルは auto.Pass3ShotDetail.k1..k8)
 *   - 折り畳み 7 種: short_service / long_service / defensive / slice /
 *     cant_reach / flick / block
 *     (ShotType 正規値。ラベルは既存 shot_types.* を流用)
 *     ※ other は「後で詳細入力」ボタンとして提供 (保存値 'other')
 *
 *   スマッシュ統合 (2026-11): 以前は around_head / half_smash も折り畳みに出して
 *     いたが、入力では smash に一本化し選択肢から外した。これら canonical 値は
 *     既存行・解析のため温存され、保存は canonical "smash" になる。around_head は
 *     is_around_head 属性で別途記録できる。既存行が持つ around_head / half_smash は
 *     一覧チップのラベル表示のみ labelForShot に残して壊さない。
 */
import { useMemo, useState } from 'react'
import { AnnotateOverlay, ZoneCode } from './AnnotateOverlay'
import type { Quad, CourtHalf } from '@/utils/courtHomography'
import { enqueue } from '@/utils/mobileAnnotateQueue'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { normalizeStrikerTeam, nextStrikingTeam, teamLetter } from '@/utils/players'
import { resolveHitter, slotsOfTeam, type HitterSlot } from '@/utils/mobileAnnotateDoubles'
import { SERVICE_TYPES, asZoneCode, isServeDowngrade, strokeValidationError } from '@/utils/mobileStrokeValidation'
import { isShotKey, type ShotSuggestion } from '@/utils/mobileAnnotateShotSuggest'

// Build inside the component via useMemo so t() is bound to the current
// i18next instance. Defining this at module scope crashes the minified
// bundle with "ReferenceError: t is not defined" (t exists only in the
// useTranslation() hook context).
// 固定 8 種は backend の canonical ShotType 値で保存する (net/push/lift/cross の
// 非正規値だと個別 POST/PUT が canonicalize せず DB に生値が残り、desktop の
// shot_types.* ラベル解決や分析と不整合になる)。ラベルは位置依存の k1..k8 を流用
// するため key を canonical にしても表示文言は変わらない。
const COMMON_SHOT_KEYS = ['smash','clear','drop','net_shot','push_rush','drive','lob','cross_net'] as const

// 「その他」展開で表示する残りの球種 (ShotType 正規値)。other は別途
// 「後で詳細入力」ボタンで扱うため、グリッドには含めない。
// スマッシュ統合 (2026-11): 入力では smash 系を COMMON の 'smash' 1 つに束ねる。
// around_head / half_smash は入力選択肢から外した（canonical 値自体は既存行・
// 解析のため温存。保存は canonical "smash" 固定）。around_head は is_around_head
// 属性で別途記録できる。これによりグリッドは 7 種になる。
// 8(固定) + 7(グリッド) + 1(other ボタン) = 16 入力選択肢。残る canonical
// (around_head / half_smash) は新規入力では出さないが DB/解析では有効。
const OTHER_SHOT_KEYS = [
  'short_service','long_service','defensive','slice',
  'cant_reach','flick','block',
] as const

type ShotKey = typeof COMMON_SHOT_KEYS[number] | typeof OTHER_SHOT_KEYS[number]

// 送信前検証 (backend/utils/validators.py と同じルール) は utils に切り出した。
// 422 → mobileAnnotateQueue の manualRetry 化による「無言ドロップ」を防ぐ。

interface StrokeLite {
  id?: number | null
  stroke_num: number
  player: HitterSlot
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
  /** ダブルス: 追加する球の打球者を個人 slot (partner を含む) で選ばせて保存する */
  doubles?: boolean
  /**
   * 保存済みコート校正 (先頭 4 隅)。渡すと AnnotateOverlay が撮影方向に合わせた
   * タップ判定を行う。null / 未指定のときは従来の固定枠で動く。
   */
  courtQuad?: Quad | null
  /** 校正を使うとき、入力片面が画面の near/far どちらに写っているか。既定 'near'。 */
  courtHalf?: CourtHalf
  /** 「動画に戻って校正する」導線 (未校正バナーから呼ぶ)。未指定なら案内を出さない。 */
  onNeedCalibration?: () => void
  /**
   * CV 由来の着地ゾーン候補 (stroke_num -> ZoneCode)。渡すと追加時の着地点入力で
   * 候補ゾーンを initialZone として先出しする (人が確定するまで保存しない)。
   * 未校正・モデル無しで null / 空のときは従来どおり初期選択なし。
   */
  landZoneSuggestions?: ReadonlyMap<number, ZoneCode> | null
  /**
   * v2: next shot_type candidates keyed by the PREVIOUS stroke shot_type. When adding a stroke,
   * the top-3 for the previous shot are surfaced as the first chips (never pre-selected).
   * null / empty (insufficient data, or player role) => full 18-chip grid as before.
   */
  shotTypeSuggestions?: ReadonlyMap<string, ShotSuggestion[]> | null
  onStrokeAdded: (s: StrokeLite) => void
  onStrokeUpdated: (s: StrokeLite) => void
  onClose: () => void
}

export function Pass3ShotDetail({
  rally,
  strokes,
  doubles = false,
  courtQuad = null,
  courtHalf = 'near',
  onNeedCalibration,
  landZoneSuggestions = null,
  shotTypeSuggestions = null,
  onStrokeAdded,
  onStrokeUpdated,
  onClose,
}: Props) {
  const { t } = useTranslation()
  // 固定 8 種: 既存の保存値を維持しつつラベルは k1..k8 を流用。
  const COMMON_SHOTS = useMemo(
    () => COMMON_SHOT_KEYS.map((key, idx) => ({ key, label: t(`auto.Pass3ShotDetail.k${idx + 1}`) })),
    [t],
  )
  // 折り畳み 10 種: 正規 ShotType 値。ラベルは既存 shot_types.* を流用。
  const OTHER_SHOTS = useMemo(
    () => OTHER_SHOT_KEYS.map((key) => ({ key, label: t(`shot_types.${key}`) })),
    [t],
  )
  // 一覧表示でラベルを引く用の統合マップ (固定 + 折り畳み)。
  // スマッシュ統合で入力グリッドからは外した around_head / half_smash も、
  // 既存行 (old rows) の chip ラベル表示 (下部の labelForShot.get(s.shot_type))
  // が壊れないよう、表示ラベルだけはここに残す。入力選択肢 (COMMON_SHOTS /
  // OTHER_SHOTS) には含めないので、新規入力でこれらが選べるわけではない。
  const labelForShot = useMemo(() => {
    const map = new Map<string, string>()
    COMMON_SHOTS.forEach((c) => map.set(c.key, c.label))
    OTHER_SHOTS.forEach((c) => map.set(c.key, c.label))
    // 旧データ互換の表示専用ラベル（入力には出さない）。
    for (const legacy of ['around_head', 'half_smash'] as const) {
      if (!map.has(legacy)) map.set(legacy, t(`shot_types.${legacy}`))
    }
    return map
  }, [COMMON_SHOTS, OTHER_SHOTS, t])

  // 入力で実際に選べる shot_type キー集合（COMMON + OTHER + 'other'）。
  // 遷移提案 (shotSuggestFor) はこの集合に含まれる候補のみ出す。スマッシュ統合で
  // 外した around_head / half_smash は labelForShot には表示用に残るが、ここには
  // 入らないため提案チップには現れない（新規入力は smash に一本化）。
  const inputableShotKeys = useMemo(() => {
    const s = new Set<string>(['other'])
    COMMON_SHOT_KEYS.forEach((k) => s.add(k))
    OTHER_SHOT_KEYS.forEach((k) => s.add(k))
    return s
  }, [])

  // v2: resolve top-3 next shot_type candidates for a given previous shot_type into
  // label-carrying, badge-ready chip options. Returns [] when there is no suggestion
  // (insufficient support, out-of-vocab prev, or suggestions disabled for the role).
  const shotSuggestFor = (prevShot: string | null | undefined): Array<{ key: ShotKey | 'other'; label: string; tier: string }> => {
    if (!shotTypeSuggestions || !isShotKey(prevShot)) return []
    const cands = shotTypeSuggestions.get(prevShot)
    if (!cands || cands.length === 0) return []
    return cands
      .filter((c) => inputableShotKeys.has(c.shot_type))
      .map((c) => ({ key: c.shot_type as ShotKey | 'other', label: labelForShot.get(c.shot_type) ?? c.shot_type, tier: c.decision_mode }))
  }
  const sorted = useMemo(
    () => [...strokes].sort((a, b) => a.stroke_num - b.stroke_num),
    [strokes],
  )

  // 「追加モード」: shot 選択 → hit_zone → land_zone
  type AddState =
    | { phase: 'idle' }
    | { phase: 'pickHitter' }
    | { phase: 'pickShot' }
    | { phase: 'hitZone'; shot: ShotKey | 'other' }
    | { phase: 'landZone'; shot: ShotKey | 'other'; hit: ZoneCode }
  const [add, setAdd] = useState<AddState>({ phase: 'idle' })

  // shot_type 更新中の stroke (= 既存 chip タップ)
  const [editingStrokeNum, setEditingStrokeNum] = useState<number | null>(null)
  // 編集 wizard の途中状態 (球種選択後に 打点 → 着地点 を既存値入りで選び直す)
  type EditDraft =
    | { phase: 'hitZone'; shot: ShotKey | 'other' }
    | { phase: 'landZone'; shot: ShotKey | 'other'; hit: ZoneCode | null }
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null)
  const cancelEdit = () => {
    setEditDraft(null)
    setEditingStrokeNum(null)
  }
  // 送信前検証で弾いた場合のユーザー向けエラー (無言ドロップの代わりに明示表示)。
  const [commitError, setCommitError] = useState<string | null>(null)

  // Pass 2 が "final" を sentinel 9999 で挿入するので、その手前に詰める。
  // 最終打は stroke_num>=9000 の一時番号だけでなく、未分類の最終打 (shot_type が
  // __final_pending) も同じ最終打として扱う。Pass3 を閉じると最終打は通常番号へ再採番されて
  // 一時番号の目印を失うが、再編集で追加した中間球は必ずその手前へ入れる (#760)。
  const isFinalStroke = (s: StrokeLite) => s.stroke_num >= 9000 || s.shot_type === '__final_pending'
  const finalSentinel = [...sorted].reverse().find(isFinalStroke) || null
  const intermediates = sorted.filter((s) => s !== finalSentinel)
  const nextStrokeNum = (intermediates[intermediates.length - 1]?.stroke_num ?? 0) + 1
  // 再採番済みの最終打 (番号が次の中間球と衝突する) は、追加前に 1 つ後ろへずらす必要がある。
  const finalNeedsShift = finalSentinel != null && finalSentinel.stroke_num < 9000 && finalSentinel.stroke_num <= nextStrokeNum
  // 前 stroke の player の逆。
  // ダブルスの stroke は player が partner_a / partner_b にもなるので、
  // 素直に反転すると `partner_a` !== `player_a` から `player_a` が返り、
  // **同じチームに打ち返したことになる**。チームへ正規化してから反転する。
  // 追加する球は最終打の手前に入るので、直前の「中間球」(無ければサーブ側) の相手が打つ。
  const nextPlayer: 'player_a' | 'player_b' = nextStrikingTeam(
    intermediates[intermediates.length - 1]?.player, rally.server,
  )
  // ダブルスは追加前に選ばれた個人 slot。シングルスは nextPlayer のまま。
  const [hitterSlot, setHitterSlot] = useState<HitterSlot | null>(null)
  const nextHitter = resolveHitter(doubles, nextPlayer, hitterSlot)

  const commitShot = async (shotKey: ShotKey | 'other', hit: ZoneCode | null, land: ZoneCode | null) => {
    if (!nextHitter) {
      setAdd({ phase: 'pickHitter' })
      return
    }
    // 再採番済みの最終打は、追加する中間球に番号を譲るため先に 1 つ後ろへずらす。
    // サーバ id が無い (未送信) 最終打は PUT できないので、保存させずエラーを見せる。
    if (finalNeedsShift && finalSentinel && !finalSentinel.id) {
      setCommitError(t('auto.Pass3ShotDetail.err_final_not_saved'))
      setAdd({ phase: 'idle' })
      return
    }
    // 送信前検証: backend validate_stroke を必ず通る形だけ送る。弾かれる組合せを
    // そのまま POST すると 422 → queue が manualRetry 化し、入力が無言で失われるため。
    const verr = strokeValidationError(shotKey, land, nextStrokeNum)
    if (verr) {
      setCommitError(t(`auto.Pass3ShotDetail.err_${verr}`))
      setAdd({ phase: 'idle' })
      return
    }
    setCommitError(null)
    // enqueue (IndexedDB への積み込み) 失敗を握り潰さない。失敗したら onStrokeAdded を
    // 呼ばず (= 幻の打を画面に出さず) commitError を立て、ユーザーに再入力を促す (監査 #623)。
    try {
      if (finalNeedsShift && finalSentinel && finalSentinel.id) {
        // 同じ rally の操作は enqueue 順に送られるため、ずらす PUT を先に積めば
        // 中間球の POST が最終打と同じ番号で衝突しない。
        const shifted = nextStrokeNum + 1
        await enqueue('PUT /api/strokes/:id', {
          stroke_num: shifted,
          player: finalSentinel.player,
          shot_type: finalSentinel.shot_type,
          hit_zone: finalSentinel.hit_zone,
          land_zone: finalSentinel.land_zone,
        }, { id: finalSentinel.id }, { sequenceKey: `rally:${rally.id}` })
        onStrokeUpdated({ ...finalSentinel, stroke_num: shifted })
      }
      const body = {
        stroke_num: nextStrokeNum,
        player: nextHitter,
        shot_type: shotKey,
        hit_zone: hit,
        land_zone: land,
      }
      await enqueue('POST /api/strokes?rally_id=:rally_id', body, { rally_id: rally.id })
      onStrokeAdded({
        id: null,
        stroke_num: nextStrokeNum,
        player: nextHitter,
        shot_type: shotKey,
        hit_zone: hit,
        land_zone: land,
        pending: true,
      })
      // rally.rally_length を「中間ストローク + 最終打 (sentinel が居れば +1)」に更新
      const newLength = nextStrokeNum + (finalSentinel ? 1 : 0)
      await enqueue('PUT /api/rallies/:id', { rally_length: newLength }, { id: rally.id })
    } catch {
      setCommitError(t('auto.Pass3ShotDetail.enqueue_failed'))
      setAdd({ phase: 'idle' })
      return
    }
    setAdd({ phase: 'idle' })
  }

  /**
   * sentinel(9999) の最終打点 stroke を「中間 stroke の最大番号 + 1」へ再採番する (5b 対応)。
   *
   * Pass2 は最終打点を stroke_num=9999 の sentinel として作る (Pass3 で中間 stroke を
   * 挿入する余地を空けるため)。中間 stroke 挿入後、この sentinel を詰めて連番化しないと
   * stroke_num に 9999 の巨大ギャップが残り、rally 内のストローク順序が壊れる。
   * backend には renumber 処理が無い (POST/PUT は stroke_num を verbatim 保存) ため、
   * フロントで Pass3 完了時に明示的に補正する。
   *
   * 条件:
   *   - sentinel が存在し、サーバ id を持つ (PUT には id が必須。未 flush の pending は
   *     id 未確定なので renumber できない → スキップ。次回 Pass3 を開いた際に id が
   *     付いた状態で再実行される)。
   *   - sentinel が未採番 (stroke_num >= 9000)。既に詰め済みなら二重処理しない。
   *   - 目標番号が現在値と異なる。
   *
   * 併せて rally.rally_length を実数 (= 最終 stroke_num) に更新する。
   * stroke_type / データモデルは変更しない (stroke_num のみ補正)。
   */
  const renumberSentinelAndFinalize = async () => {
    if (!finalSentinel) return
    // サーバ id が無い (= まだ flush 前の pending) 場合は renumber 不可。
    if (!finalSentinel.id) return
    // 既に詰め済み (< 9000) なら何もしない。
    if (finalSentinel.stroke_num < 9000) return
    // 中間 stroke の最大番号 + 1。中間が無ければ 1 (= serve のみ → final が 1 番)。
    const maxIntermediate = intermediates.length > 0
      ? intermediates[intermediates.length - 1].stroke_num
      : 0
    const targetNum = maxIntermediate + 1
    if (targetNum === finalSentinel.stroke_num) return
    // sentinel を targetNum へ再採番 (PUT は full body 要求)。
    await enqueue('PUT /api/strokes/:id', {
      stroke_num: targetNum,
      player: finalSentinel.player,
      shot_type: finalSentinel.shot_type,
      hit_zone: finalSentinel.hit_zone,
      land_zone: finalSentinel.land_zone,
    }, { id: finalSentinel.id }, { sequenceKey: `rally:${rally.id}` })
    // rally_length を実数 (= 最終 stroke の番号 = targetNum) に更新。
    await enqueue('PUT /api/rallies/:id', { rally_length: targetNum }, { id: rally.id })
    // 画面側の stroke_num は 2 件とも積めた後で更新する。1 件目だけ積めて 2 件目が失敗した場合、
    // 先に更新すると再試行時に sentinel が詰め済みに見えて rally_length の更新が二度と積まれない。
    onStrokeUpdated({ ...finalSentinel, stroke_num: targetNum })
  }

  // 最終化が成功したときだけ閉じる。失敗時は画面に残してエラーを見せ、もう一度閉じる操作で再試行できる。
  const handleClose = async () => {
    try {
      await renumberSentinelAndFinalize()
    } catch {
      setCommitError(t('auto.Pass3ShotDetail.err_finalize_failed'))
      return
    }
    onClose()
  }

  const editStroke = async (
    strokeNum: number,
    shotKey: ShotKey | 'other',
    newHit: string | null,
    newLandRaw: string | null,
  ) => {
    const s = strokes.find((x) => x.stroke_num === strokeNum)
    if (!s || !s.id) {
      cancelEdit()
      return
    }
    // cant_reach は着地点を持てない → land_zone をクリアしてから送る。
    const newLand = shotKey === 'cant_reach' ? null : newLandRaw
    if (isServeDowngrade(s.stroke_num, s.shot_type, shotKey)) {
      setCommitError(t('auto.Pass3ShotDetail.err_serve_locked'))
      cancelEdit()
      return
    }
    const verr = strokeValidationError(shotKey, asZoneCode(newLand), s.stroke_num)
    if (verr) {
      setCommitError(t(`auto.Pass3ShotDetail.err_${verr}`))
      cancelEdit()
      return
    }
    setCommitError(null)
    // PUT /api/strokes/:id は StrokeData full body を要求する。球種・打点・着地点を
    // 1 件の PUT にまとめて送る (変更しない項目は現値のまま)。
    await enqueue('PUT /api/strokes/:id', {
      stroke_num: s.stroke_num,
      player: s.player,
      shot_type: shotKey,
      hit_zone: newHit,
      land_zone: newLand,
    }, { id: s.id }, { sequenceKey: `rally:${rally.id}` })
    onStrokeUpdated({ ...s, shot_type: shotKey, hit_zone: newHit, land_zone: newLand })
    cancelEdit()
  }

  // overlay プロンプト用に shot キーを表示ラベルへ解決 (other は専用ラベル)。
  const shotLabel = (k: ShotKey | 'other'): string =>
    k === 'other' ? t('auto.Pass3ShotDetail.other_later') : (labelForShot.get(k) ?? k)

  // --- 追加 wizard 中の overlay 出し分け ---
  if (add.phase === 'hitZone') {
    return (
      <AnnotateOverlay
        key="add-hit"
        prompt={t('auto.Pass3ShotDetail.prompt_hit_zone', { n: nextStrokeNum, shot: shotLabel(add.shot) })}
        courtQuad={courtQuad}
        half={courtHalf}
        primaryLabel={t('auto.Pass3ShotDetail.next')}
        onCommit={(z) => setAdd({ phase: 'landZone', shot: add.shot, hit: z })}
        onCancel={() => setAdd({ phase: 'idle' })}
      />
    )
  }
  if (add.phase === 'landZone') {
    return (
      <AnnotateOverlay
        key="add-land"
        prompt={t('auto.Pass3ShotDetail.prompt_land_zone', { n: nextStrokeNum, shot: shotLabel(add.shot) })}
        courtQuad={courtQuad}
        half={courtHalf}
        primaryLabel={t('auto.Pass3ShotDetail.save')}
        initialZone={landZoneSuggestions ? landZoneSuggestions.get(nextStrokeNum) ?? null : null}
        onCommit={(z) => void commitShot(add.shot, add.hit, z)}
        onCancel={() => setAdd({ phase: 'idle' })}
      />
    )
  }
  if (add.phase === 'pickHitter') {
    return (
      <div className="absolute inset-0 bg-black/95 flex flex-col">
        <div className="px-3 py-2 border-b border-gray-800 text-xs text-yellow-200 font-bold">
          {t('auto.Pass3ShotDetail.pick_hitter_title', { n: nextStrokeNum, player: nextPlayer === 'player_a' ? 'A' : 'B' })}
        </div>
        <div className="flex-1 p-3 grid grid-cols-2 gap-2 content-start" role="radiogroup" aria-label={t('auto.Pass3ShotDetail.pick_hitter_label')}>
          {slotsOfTeam(nextPlayer).map((slot) => (
            <button
              key={slot}
              type="button"
              role="radio"
              aria-checked={hitterSlot === slot}
              onClick={() => {
                setHitterSlot(slot)
                setAdd({ phase: 'pickShot' })
              }}
              className="px-3 py-3 rounded-lg bg-gray-800 hover:bg-gray-700 text-white text-sm font-medium"
              style={{ minHeight: '52px' }}
            >
              {t(`auto.HitterSlot.${slot}`)}
            </button>
          ))}
        </div>
        <div className="px-3 py-2 border-t border-gray-800">
          <button type="button" onClick={() => setAdd({ phase: 'idle' })} className="px-3 py-1.5 rounded bg-gray-700 text-white text-xs">
            {t('auto.Pass3ShotDetail.cancel')}
          </button>
        </div>
      </div>
    )
  }
  if (add.phase === 'pickShot') {
    return (
      <ShotChipPicker
        title={t('auto.Pass3ShotDetail.pick_title', { n: nextStrokeNum, player: nextPlayer === 'player_a' ? 'A' : 'B' })}
        suggestions={shotSuggestFor(intermediates[intermediates.length - 1]?.shot_type)}
        commonShots={COMMON_SHOTS}
        otherShots={OTHER_SHOTS}
        allowServices={nextStrokeNum === 1}
        onPick={(k) => {
          // cant_reach (届かず) は着地点を持てない → zone wizard を飛ばして即確定。
          if (k === 'cant_reach') { void commitShot('cant_reach', null, null); return }
          setAdd({ phase: 'hitZone', shot: k })
        }}
        onCancel={() => setAdd({ phase: 'idle' })}
      />
    )
  }
  if (editingStrokeNum != null) {
    const editing = strokes.find((x) => x.stroke_num === editingStrokeNum)
    if (editDraft?.phase === 'hitZone') {
      return (
        <AnnotateOverlay
          key="edit-hit"
          prompt={t('auto.Pass3ShotDetail.prompt_hit_zone', { n: editingStrokeNum, shot: shotLabel(editDraft.shot) })}
          courtQuad={courtQuad}
          half={courtHalf}
          primaryLabel={t('auto.Pass3ShotDetail.next')}
          initialZone={asZoneCode(editing?.hit_zone)}
          onCommit={(z) => setEditDraft({ phase: 'landZone', shot: editDraft.shot, hit: z })}
          onCancel={cancelEdit}
        />
      )
    }
    if (editDraft?.phase === 'landZone') {
      return (
        <AnnotateOverlay
          key="edit-land"
          prompt={t('auto.Pass3ShotDetail.prompt_land_zone', { n: editingStrokeNum, shot: shotLabel(editDraft.shot) })}
          courtQuad={courtQuad}
          half={courtHalf}
          primaryLabel={t('auto.Pass3ShotDetail.save')}
          initialZone={asZoneCode(editing?.land_zone)}
          onCommit={(z) => void editStroke(editingStrokeNum, editDraft.shot, editDraft.hit, z)}
          onCancel={cancelEdit}
        />
      )
    }
    return (
      <ShotChipPicker
        title={t('auto.Pass3ShotDetail.edit_title', { n: editingStrokeNum })}
        commonShots={COMMON_SHOTS}
        otherShots={OTHER_SHOTS}
        allowServices={editingStrokeNum === 1}
        serviceOnly={editingStrokeNum === 1 && isServeDowngrade(1, editing?.shot_type, 'smash')}
        onPick={(k) => {
          // cant_reach は着地点を持てない → ゾーン選択を飛ばし、打点は現値のまま即確定。
          if (k === 'cant_reach') {
            void editStroke(editingStrokeNum, k, editing?.hit_zone ?? null, null)
            return
          }
          setEditDraft({ phase: 'hitZone', shot: k })
        }}
        onCancel={cancelEdit}
      />
    )
  }

  // --- 一覧 + 追加ボタン ---
  return (
    <div className="absolute inset-0 bg-black/90 flex flex-col">
      <div className="bg-black/95 px-3 py-2 flex items-center gap-3 border-b border-gray-800 text-xs">
        <div className="text-yellow-200 font-bold">
          {t('auto.Pass3ShotDetail.header', { rally: rally.rally_num, set: rally.set_num })}
        </div>
        <div className="flex-1" />
        <div className="text-gray-400">{t('auto.Pass3ShotDetail.stroke_count', { n: sorted.length })}</div>
        <button
          type="button"
          onClick={() => void handleClose()}
          className="px-2 py-1 rounded bg-gray-700 text-white text-[10px]"
        >
          {t('auto.Pass3ShotDetail.close')}
        </button>
      </div>

      {commitError && (
        <div className="bg-red-900/80 text-red-100 text-xs px-3 py-2 flex items-center gap-2 border-b border-red-700">
          <MIcon name="error" size={14} />
          <span className="flex-1">{commitError}</span>
          <button type="button" onClick={() => setCommitError(null)} className="text-red-200 underline">
            {t('auto.Pass3ShotDetail.dismiss')}
          </button>
        </div>
      )}

      {/* 未校正の案内 (入力の邪魔にならない細いバナー)。校正があれば撮影方向に合わせて
         タップできる旨と、動画に戻って校正する導線。courtQuad があるときは出さない。 */}
      {!courtQuad && onNeedCalibration && (
        <div className="bg-sky-950/80 text-sky-100 text-[11px] px-3 py-1.5 flex items-center gap-2 border-b border-sky-800">
          <MIcon name="info" size={13} />
          <span className="flex-1">{t('auto.Pass3ShotDetail.calib_hint')}</span>
          <button type="button" onClick={onNeedCalibration} className="px-2 py-1 rounded bg-sky-800 text-sky-50">
            {t('auto.Pass3ShotDetail.calib_cta')}
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3 space-y-2" data-tutorial="mobileAnnotate.strokeChips">
        {sorted.length === 0 && (
          <div className="text-gray-500 text-sm text-center py-4">
            {t('auto.Pass3ShotDetail.empty_hint')}
          </div>
        )}
        {sorted.map((s) => (
          <button
            key={s.id ?? `n${s.stroke_num}`}
            type="button"
            onClick={() => setEditingStrokeNum(s.stroke_num)}
            className="w-full flex items-center gap-3 px-3 py-2 rounded bg-gray-800 hover:bg-gray-700"
          >
            <span className="font-mono text-[11px] text-gray-400">#{s.stroke_num}</span>
            <span className={`text-xs font-bold ${
              normalizeStrikerTeam(s.player) === 'player_a' ? 'text-blue-400' : 'text-pink-400'
            }`}>
              {doubles ? t(`auto.HitterSlot.${s.player}`) : teamLetter(s.player)}
            </span>
            <span className="text-xs">
              {labelForShot.get(s.shot_type)
                ?? (s.shot_type === '__final_pending' ? t('auto.Pass3ShotDetail.final_unclassified')
                : s.shot_type === 'serve' ? t('shot_categories.serve')
                : s.shot_type)}
            </span>
            <div className="flex-1" />
            <span className="font-mono text-[10px] text-gray-500">
              {s.hit_zone ?? '-'} → {s.land_zone ?? '-'}
            </span>
            {s.pending && (
              <span className="text-xs text-amber-400">{t('auto.Pass3ShotDetail.pending')}</span>
            )}
          </button>
        ))}

        {/* 追加ボタン */}
        <button
          type="button"
          onClick={() => {
            // ダブルスは毎回打球者を選び直させる (前の球の slot を引き継がない)
            setHitterSlot(null)
            setAdd({ phase: doubles ? 'pickHitter' : 'pickShot' })
          }}
          data-tutorial="mobileAnnotate.addStroke"
          className="w-full px-3 py-3 rounded-lg border-2 border-dashed border-gray-600 text-gray-300 text-sm hover:bg-gray-800"
        >
          {t('auto.Pass3ShotDetail.add_stroke', { n: nextStrokeNum, player: nextPlayer === 'player_a' ? 'A' : 'B' })}
        </button>
      </div>
    </div>
  )
}


interface ShotOption {
  key: ShotKey
  label: string
}

function ShotChipPicker({
  title,
  suggestions = [],
  commonShots,
  otherShots,
  allowServices,
  serviceOnly = false,
  onPick,
  onCancel,
}: {
  title: string
  /** 上部に常時表示する固定 8 種 */
  commonShots: ShotOption[]
  /** 「その他」展開で表示する残り 10 種 (other ボタンは別枠) */
  otherShots: ShotOption[]
  /** サーブ種別 (short/long_service) を出すか。ラリー1球目のみ true (validate_stroke 準拠)。 */
  allowServices: boolean
  /** 1球目のサーブを編集中: サーブ種別だけ選べる (非サーブへの変更を UI で出さない, 監査 #795)。 */
  serviceOnly?: boolean
  onPick: (key: ShotKey | 'other') => void
  /** v2: next shot_type candidates to surface at the FRONT (already label-resolved). Empty = none. */
  suggestions?: Array<{ key: ShotKey | 'other'; label: string; tier: string }>
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [showOther, setShowOther] = useState(false)
  // 1球目以外ではサーブ種別を隠す (送っても 422 で無言ドロップするため)。
  const visibleOther = useMemo(() => {
    if (serviceOnly) return otherShots.filter((o) => SERVICE_TYPES.includes(o.key))
    return allowServices ? otherShots : otherShots.filter((o) => !SERVICE_TYPES.includes(o.key))
  }, [otherShots, allowServices, serviceOnly])
  const visibleCommon = serviceOnly ? [] : commonShots
  return (
    <div className="absolute inset-0 bg-black/95 flex flex-col">
      <div className="px-3 py-2 border-b border-gray-800 text-xs text-yellow-200 font-bold">
        {title}
      </div>
      <div className="flex-1 overflow-y-auto p-3 content-start">
        {/* v2 next-shot candidates: top-3 surfaced at the FRONT. Never pre-selected;
            always marked as "candidate" with a confidence badge so a wrong one is noticed.
            Tapping confirms via the same onPick as a manual chip (no silent difference). */}
        {suggestions.length > 0 && (
          <div className="mb-3">
            <div className="text-[10px] text-sky-300 font-bold mb-1 flex items-center gap-1">
              <MIcon name="auto_awesome" size={12} />
              <span>{t('auto.Pass3ShotDetail.suggest_title')}</span>
            </div>
            <div className="grid grid-cols-2 gap-2" data-testid="shot-suggestions">
              {suggestions.map((sg) => (
                <button
                  key={`sg-${sg.key}`}
                  type="button"
                  onClick={() => onPick(sg.key)}
                  data-suggested="true"
                  className="relative px-3 py-3 rounded-lg bg-sky-900/40 border border-sky-500 text-sky-50 text-sm font-medium text-left"
                  style={{ minHeight: '52px' }}
                >
                  <span className="absolute top-1 right-1 text-[9px] px-1 rounded bg-sky-700 text-sky-50">
                    {t(`auto.Pass3ShotDetail.tier_${sg.tier}`)}
                  </span>
                  <span className="block">{sg.label}</span>
                  <span className="block text-[9px] text-sky-300">{t('auto.Pass3ShotDetail.suggest_badge')}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {/* 固定 8 種: 誤タップ回避で 52px 高・2 カラム */}
        <div className="grid grid-cols-2 gap-2">
          {visibleCommon.map((c) => (
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
        </div>

        {/* 「その他」折り畳みトグル */}
        <button
          type="button"
          onClick={() => setShowOther((v) => !v)}
          aria-expanded={showOther}
          className="mt-3 w-full flex items-center justify-center gap-1 px-3 py-2 rounded-lg bg-gray-700/60 hover:bg-gray-700 text-gray-200 text-xs"
          style={{ minHeight: '44px' }}
        >
          <span>{t('auto.Pass3ShotDetail.show_other')}</span>
          <MIcon name={showOther ? 'expand_less' : 'expand_more'} size={18} />
        </button>

        {showOther && (
          <div className="mt-2 grid grid-cols-2 gap-2">
            {visibleOther.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => onPick(c.key)}
                className="px-3 py-3 rounded-lg bg-gray-800 hover:bg-gray-700 text-white text-sm font-medium"
                style={{ minHeight: '48px' }}
              >
                {c.label}
              </button>
            ))}
            {/* other は「後で詳細入力」として全幅で提供 (保存値 'other') */}
            {!serviceOnly && (
              <button
                type="button"
                onClick={() => onPick('other')}
                className="col-span-2 px-3 py-2 rounded-lg bg-gray-700 text-gray-200 text-xs"
                style={{ minHeight: '44px' }}
              >
                {t('auto.Pass3ShotDetail.other_later')}
              </button>
            )}
          </div>
        )}
      </div>
      <div className="px-3 py-2 border-t border-gray-800">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded bg-gray-700 text-white text-xs"
        >
          {t('auto.Pass3ShotDetail.cancel')}
        </button>
      </div>
    </div>
  )
}
