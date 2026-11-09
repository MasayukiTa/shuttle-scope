import { create } from 'zustand'
import { ShotType, StrokeInput, Zone9, LandZone, ZoneNet } from '@/types'
import type { SyncState } from '@/utils/syncStatus'

export type InputStep =
  | 'idle'        // 待機中（ショットキーでラリー開始）
  | 'land_zone'   // 落点選択待ち（ショット入力直後）
  | 'rally_end'   // ラリー終了確認中

export interface PendingStroke {
  shot_type?: ShotType
  hit_zone?: Zone9
  /** Phase A: CV 自動推定値 (人間 override 前のオリジナル) */
  hit_zone_cv?: Zone9 | null
  /** Phase A: 'cv' = CV 値そのまま / 'manual' = 人間 override */
  hit_zone_source?: 'cv' | 'manual' | 'carried_over'
  land_zone?: LandZone
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  /** 仙台大要望: 打球の高さ 4 段階 (0..3)。任意。未選択なら undefined。 */
  hit_height?: number
  timestamp_sec?: number
}

// K-002: 保存キュー
export interface SaveError {
  rallyNum: number
  error: string
}

// #664: 直前に確定したラリーを取り消すために、確定の「前」に capture しておく値。
// confirmRally は確定時に strokes を捨てるので、取り消し復元に必要な値は呼び出し側で保持する。
export interface ConfirmedRallySnapshot {
  scoreA: number
  scoreB: number
  /** 確定したラリーの番号（= 取り消し後に戻すべき currentRallyNum）。 */
  rallyNum: number
  /** 確定したラリーのサーバ（= 取り消し後に戻すべき currentPlayer）。 */
  server: 'player_a' | 'player_b'
}

interface AnnotationState {
  // セット管理
  matchId: number | null
  currentSetId: number | null
  currentSetNum: number

  // ラリー状態
  currentRallyNum: number
  scoreA: number
  scoreB: number
  isRallyActive: boolean
  rallyStartTimestamp: number | null

  // ストローク入力
  currentStrokes: StrokeInput[]
  pendingStroke: PendingStroke
  inputStep: InputStep
  currentStrokeNum: number
  currentPlayer: 'player_a' | 'player_b'  // 現在打球するチーム側（= 次ラリーのサーバー）
  isDoubles: boolean                        // ダブルスモード
  currentHitter: string                     // 実際の打者: player_a | partner_a | player_b | partner_b

  // アンドゥ（最大10件）
  undoStack: StrokeInput[]

  // #784: 直近ラリーの勝敗履歴（解析モードの momentum 表示用）。confirmRally / skipRallyState で追記する。
  recentRallyResults: Array<{ winner: 'player_a' | 'player_b' }>

  // K-002: 保存キュー状態
  pendingSaveCount: number
  saveErrors: SaveError[]

  // unsent-indicator: サーバー未送信ラリー (IndexedDB owned キュー) の件数と送信状態。
  // IndexedDB の実データ由来で useOfflineSync が都度上書きするため、試合リセット
  // (init / clearMatch 等) では 0 に戻さない。
  unsentCount: number
  syncState: SyncState

  // Phase C speed: セミ自動 flip 制御
  // 'auto'      = 既存挙動 (常に flip)
  // 'semi-auto' = flip するが 500ms 以内の次ショット tap で revert
  // 'manual'    = flip しない (打者 tap が常に必要)
  flipMode: 'auto' | 'semi-auto' | 'manual'
  /** 直前 flip の時刻 (semi-auto の bounce 判定用) */
  lastFlipAt: number | null
  /** flip 直前の player (revert 用) */
  playerBeforeFlip: 'player_a' | 'player_b' | null

  // アクション
  init: (
    matchId: number,
    setId: number,
    setNum: number,
    rallyNum: number,
    scoreA: number,
    scoreB: number,
    initialServer?: 'player_a' | 'player_b'
  ) => void
  setCurrentSet: (setId: number, setNum: number) => void
  /** 別の試合へ移るとき、前の試合のスコア/セット/ラリー/入力途中を破棄する (A-11) */
  clearMatch: () => void
  // K-002: 保存キュー操作
  incrementPending: () => void
  decrementPending: () => void
  addSaveError: (err: SaveError) => void
  clearSaveErrors: () => void
  // unsent-indicator: 未送信件数と送信状態を更新する (useOfflineSync が呼ぶ)。
  setSyncStatus: (unsentCount: number, syncState: SyncState) => void

  // ラリー操作
  /** 一時保存からの復元では動画位置が分からないことがある。
   *  0 を入れるとラリーが «動画の先頭で始まった» ことになり、
   *  `video_timestamp_start` としてそのまま保存されるので null を許す。 */
  startRally: (timestamp: number | null) => void
  endRallyRequest: () => void
  cancelRallyEnd: () => void

  // ストローク入力（2アクション：ショットキー → 落点入力）
  inputShotType: (shotType: ShotType, timestamp: number) => void
  selectLandZone: (zone: LandZone) => void  // 落点クリック or テンキー → 自動確定
  skipLandZone: () => void                // 落点スキップ（0キー / Numpad0）→ 自動確定
  selectHitZone: (zone: Zone9) => void    // 打点（任意で上書き）
  // Phase A: 打点を人間が override (HitZoneSelector からのタップ)
  setHitZoneOverride: (zone: Zone9) => void
  toggleAttribute: (key: 'is_backhand' | 'is_around_head') => void
  setAboveNet: (v: boolean | undefined) => void
  cycleAboveNet: () => void              // ネット上下サイクル（未指定→上→下→未指定）
  setHitHeight: (v: number | undefined) => void  // 打球の高さ 4 段階（任意・トグルで解除可）

  // プレイヤー制御
  togglePlayer: () => void
  setPlayer: (p: 'player_a' | 'player_b') => void
  // ダブルス制御
  setIsDoubles: (v: boolean) => void
  setHitter: (h: string) => void
  toggleHitterWithinTeam: () => void

  // ラリー確定（DB保存はページ側で実行）
  confirmRally: (winner: 'player_a' | 'player_b', endType: string) => StrokeInput[]
  resetRally: () => void
  // #664: 直前に確定したラリーを取り消す（LiveInputPage の誤タップ復旧用）。
  // confirmRally は確定時に strokes を捨てるため、取り消しに必要な確定前の値は
  // 呼び出し側が snapshot として渡す。スコア・ラリー番号・サーバを確定前へ戻し、
  // recentRallyResults の末尾（この確定で足した 1 件）を取り除く。ラリー入力途中
  // だった場合はクリアして idle に戻す。DB 側の削除はページが行う。
  undoLastConfirmedRally: (snapshot: ConfirmedRallySnapshot) => void

  // 見逃しラリー（ストロークなしで得点だけ記録）
  skipRallyState: (winner: 'player_a' | 'player_b') => void
  // スコア補正（スコア・ラリー番号を直接更新。API保存はページ側で行う）
  applyScoreCorrection: (scoreA: number, scoreB: number, rallyNum: number) => void

  // アンドゥ（削除したストロークを返す。呼び出し元が動画シークに使用可能）
  undoLastStroke: () => StrokeInput | null

  // ペンディング中のストロークをキャンセル（落点待ち中にEsc/Backspace/Ctrl+Z）
  cancelPendingStroke: () => void

  // G2+移動系: 直前確定ストロークのエンリッチメント更新
  updateLastStrokeEnrichment: (fields: {
    returnQuality?: string
    contactHeight?: string
    contactZone?: string
    movementBurden?: string
    movementDirection?: string
    intentTag?: string
    intentNote?: string
  }) => void

  // F-T003-01: 任意の確定ストローク (index 指定) のエンリッチメント更新。
  // 詳細分析パネルで «直前以外» のストロークを後から補完できるようにする。
  // index が範囲外のときは何もしない (壊れた入力でストローク配列を汚さない)。
  updateStrokeEnrichmentAt: (
    index: number,
    fields: {
      returnQuality?: string
      contactHeight?: string
      contactZone?: string
      movementBurden?: string
      movementDirection?: string
      intentTag?: string
      intentNote?: string
    },
  ) => void

  // セット移行
  nextSet: (setId: number, setNum: number) => void

  // Phase C speed: flip mode 設定 (localStorage 保存)
  setFlipMode: (mode: 'auto' | 'semi-auto' | 'manual') => void
}

// Phase C speed: bounce 判定窓 (ms)
const FLIP_BOUNCE_WINDOW_MS = 500
const FLIP_MODE_KEY = 'ss_flip_mode'

function loadFlipMode(): 'auto' | 'semi-auto' | 'manual' {
  if (typeof window === 'undefined') return 'semi-auto'
  try {
    const v = window.localStorage.getItem(FLIP_MODE_KEY)
    if (v === 'auto' || v === 'semi-auto' || v === 'manual') return v
  } catch { /* noop */ }
  return 'semi-auto'
}

const emptyPending = (): PendingStroke => ({
  is_backhand: false,
  is_around_head: false,
  above_net: undefined,
  hit_height: undefined,
})

// hitter id (player_a/partner_a/player_b/partner_b) → 所属チーム (player_a/player_b)。
// 文字列 suffix `_a`/`_b` 判定だと将来 '_anchor' 等で壊れるため explicit map に統一し、
// setHitter / undoLastStroke で共有する。
const HITTER_TO_TEAM: Record<string, 'player_a' | 'player_b'> = {
  player_a: 'player_a',
  partner_a: 'player_a',
  player_b: 'player_b',
  partner_b: 'player_b',
}

export const useAnnotationStore = create<AnnotationState>((set, get) => ({
  matchId: null,
  currentSetId: null,
  currentSetNum: 1,
  currentRallyNum: 1,
  scoreA: 0,
  scoreB: 0,
  isRallyActive: false,
  rallyStartTimestamp: null,
  currentStrokes: [],
  pendingStroke: emptyPending(),
  inputStep: 'idle',
  currentStrokeNum: 1,
  currentPlayer: 'player_a',
  isDoubles: false,
  currentHitter: 'player_a',
  undoStack: [],
  recentRallyResults: [],
  pendingSaveCount: 0,
  saveErrors: [],
  unsentCount: 0,
  syncState: 'saved',
  flipMode: loadFlipMode(),
  lastFlipAt: null,
  playerBeforeFlip: null,

  // K-002: 保存キュー操作
  incrementPending: () => set((s) => ({ pendingSaveCount: s.pendingSaveCount + 1 })),
  decrementPending: () => set((s) => ({ pendingSaveCount: Math.max(0, s.pendingSaveCount - 1) })),
  addSaveError: (err) => set((s) => ({ saveErrors: [...s.saveErrors, err] })),
  clearSaveErrors: () => set({ saveErrors: [] }),
  setSyncStatus: (unsentCount, syncState) =>
    set({ unsentCount: Math.max(0, Math.floor(unsentCount)), syncState }),

  init: (matchId, setId, setNum, rallyNum, scoreA, scoreB, initialServer) =>
    set({
      matchId,
      currentSetId: setId,
      currentSetNum: setNum,
      currentRallyNum: rallyNum,
      scoreA,
      scoreB,
      isRallyActive: false,
      currentStrokes: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      // initialServer は「このラリーのサーバ」。ラリー進行中は confirmRally が維持する。
      // 再開時は呼び出し側が /annotation/{id}/state の next_server
      // (= 前ラリーの勝者) を渡すこと。渡さないと player_a に戻り、
      // 以降の打者が全部ずれる (A-2)。
      currentPlayer: initialServer ?? 'player_a',
      currentHitter: initialServer ?? 'player_a',
      undoStack: [],
      recentRallyResults: [],
      pendingSaveCount: 0,
      saveErrors: [],
    }),

  setCurrentSet: (setId, setNum) =>
    set({ currentSetId: setId, currentSetNum: setNum }),

  clearMatch: () =>
    set({
      matchId: null,
      currentSetId: null,
      currentSetNum: 1,
      currentRallyNum: 1,
      scoreA: 0,
      scoreB: 0,
      isRallyActive: false,
      rallyStartTimestamp: null,
      currentStrokes: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      currentPlayer: 'player_a',
      currentHitter: 'player_a',
      undoStack: [],
      recentRallyResults: [],
      pendingSaveCount: 0,
      saveErrors: [],
    }),

  // ラリー開始: currentPlayer は前ラリー winner を引き継ぐため変更しない
  startRally: (timestamp) =>
    set({
      isRallyActive: true,
      rallyStartTimestamp: timestamp,
      currentStrokes: [],
      undoStack: [],
      currentStrokeNum: 1,
      pendingStroke: emptyPending(),
      inputStep: 'idle',
    }),

  endRallyRequest: () => set({ inputStep: 'rally_end' }),
  cancelRallyEnd: () => set({ inputStep: 'idle' }),

  // ① ショットキー押下（ラリー未開始なら自動起動）
  inputShotType: (shotType, timestamp) => {
    const { isRallyActive } = get()

    // ラリー未開始なら自動起動（currentPlayer は変えない = 前ラリー winner がサーバー）
    if (!isRallyActive) {
      set({
        isRallyActive: true,
        rallyStartTimestamp: timestamp,
        currentStrokes: [],
        undoStack: [],
        currentStrokeNum: 1,
      })
    }

    // Phase C speed: semi-auto flip の bounce revert
    // 直前 flip から 500ms 以内の連続入力 → 同じ打者の連続ショットとして扱う
    const now = Date.now()
    const stateBounce = get()
    if (
      stateBounce.flipMode === 'semi-auto'
      && stateBounce.lastFlipAt != null
      && stateBounce.playerBeforeFlip != null
      && (now - stateBounce.lastFlipAt) < FLIP_BOUNCE_WINDOW_MS
    ) {
      set({
        currentPlayer: stateBounce.playerBeforeFlip,
        currentHitter: stateBounce.playerBeforeFlip,
        playerBeforeFlip: null,
        lastFlipAt: null,
      })
    }

    // Phase A: 打点 CV 推定値を先行計算 (HitZoneSelector で preselect 表示)
    // ロジックは selectLandZone と同等: 直前ストロークの land_zone (有効な場合) を使う
    const stateNow = get()
    const prevStroke = stateNow.currentStrokes[stateNow.currentStrokes.length - 1]
    const NET_ZONES_LOCAL: ZoneNet[] = ['NET_L', 'NET_C', 'NET_R']
    const prevLandIsValid = prevStroke?.land_zone &&
      !String(prevStroke.land_zone).startsWith('OB_') &&
      !(NET_ZONES_LOCAL as string[]).includes(prevStroke.land_zone)
    const cvHitZone: Zone9 | null = prevLandIsValid
      ? (prevStroke!.land_zone as Zone9)
      : null

    // 通常: ショット入力後に落点待ち
    set((s) => ({
      pendingStroke: {
        ...s.pendingStroke,
        shot_type: shotType,
        timestamp_sec: timestamp,
        // Phase A: CV preselect 値を pendingStroke に格納
        hit_zone_cv: cvHitZone,
        hit_zone: cvHitZone ?? s.pendingStroke.hit_zone,
        // ここで入れているのは **直前の打球の着地点** = 人間が入力した値で、
        // CV の出力ではない。'cv' と記録していたため、CV を一度も走らせて
        // いない試合でも 2 打目以降が全部「機械が決めた値」として残っていた。
        // 由来を正しく書く。
        hit_zone_source: 'carried_over',
      },
      inputStep: 'land_zone',
    }))
  },

  // ② 落点ゾーン選択 → ストローク自動確定
  // OOBゾーン（'OB_'で始まる）の場合はアウト確定なのでそのままrally_endへ移行
  selectLandZone: (zone) => {
    const state = get()
    if (!state.pendingStroke.shot_type) return

    const prevStroke = state.currentStrokes[state.currentStrokes.length - 1]
    const NET_ZONES: ZoneNet[] = ['NET_L', 'NET_C', 'NET_R']
    const prevLandIsValid = prevStroke?.land_zone &&
      !String(prevStroke.land_zone).startsWith('OB_') &&
      !(NET_ZONES as string[]).includes(prevStroke.land_zone)
    const autoHitZone = prevLandIsValid
      ? (prevStroke!.land_zone as Zone9)
      : state.pendingStroke.hit_zone

    // Phase A: hit_zone_source の決定。
    // pendingStroke.hit_zone_source が既に 'manual' なら override 済として保持。
    // それ以外は直前の着地点から引き継いだ値なので 'carried_over'。
    // (CV の出力ではない。'cv' と書くと、CV を走らせていない試合でも
    //  機械由来のデータとして残ってしまう。)
    const finalHitZone = state.pendingStroke.hit_zone_source === 'manual'
      ? state.pendingStroke.hit_zone
      : autoHitZone
    const hitZoneSource: 'manual' | 'carried_over' =
      state.pendingStroke.hit_zone_source === 'manual' ? 'manual' : 'carried_over'
    const cvOriginal = state.pendingStroke.hit_zone_cv ?? autoHitZone ?? null

    const stroke: StrokeInput = {
      stroke_num: state.currentStrokeNum,
      player: state.isDoubles ? state.currentHitter : state.currentPlayer,
      shot_type: state.pendingStroke.shot_type,
      hit_zone: finalHitZone,
      hit_zone_source: hitZoneSource,
      hit_zone_cv_original: cvOriginal,
      land_zone: zone,
      is_backhand: state.pendingStroke.is_backhand,
      is_around_head: state.pendingStroke.is_around_head,
      above_net: state.pendingStroke.above_net,
      hit_height: state.pendingStroke.hit_height,
      timestamp_sec: state.pendingStroke.timestamp_sec,
    }

    // Phase C speed: flipMode に応じた次打者決定
    const willFlip = state.flipMode !== 'manual'
    const nextPlayer: 'player_a' | 'player_b' = willFlip
      ? (state.currentPlayer === 'player_a' ? 'player_b' : 'player_a')
      : state.currentPlayer

    const isOOB = String(zone).startsWith('OB_')
    const isNet = (NET_ZONES as string[]).includes(zone)

    set({
      currentStrokes: [...state.currentStrokes, stroke],
      undoStack: [...state.currentStrokes],
      currentStrokeNum: state.currentStrokeNum + 1,
      currentPlayer: nextPlayer,
      currentHitter: nextPlayer,  // 次チームの主プレイヤーにリセット
      pendingStroke: emptyPending(),
      // OOB/NETならそのままrally_end（ラリー終了確定）
      inputStep: isOOB || isNet ? 'rally_end' : 'idle',
      // Phase C speed: bounce revert 用に直前 player を覚える
      lastFlipAt: willFlip ? Date.now() : null,
      playerBeforeFlip: willFlip ? state.currentPlayer : null,
    })
  },

  // ② 落点スキップ（アウト・ネット時など） → land_zone なしで確定
  skipLandZone: () => {
    const state = get()
    if (!state.pendingStroke.shot_type) return

    const prevStroke = state.currentStrokes[state.currentStrokes.length - 1]
    // selectLandZone と同じく、前ストロークの land_zone が OB_/NET_ の場合は
    // 不正ゾーンなので hit_zone へ継承しない (継承すると Zone9 でない値が hit_zone に
    // 入り空間分析データを壊す)。
    const NET_ZONES: ZoneNet[] = ['NET_L', 'NET_C', 'NET_R']
    const prevLandIsValid = prevStroke?.land_zone &&
      !String(prevStroke.land_zone).startsWith('OB_') &&
      !(NET_ZONES as string[]).includes(prevStroke.land_zone)
    const autoHitZone = prevLandIsValid
      ? (prevStroke!.land_zone as Zone9)
      : state.pendingStroke.hit_zone

    const finalHitZone = state.pendingStroke.hit_zone_source === 'manual'
      ? (state.pendingStroke.hit_zone as Zone9 | undefined)
      : (autoHitZone as Zone9 | undefined)
    const hitZoneSource: 'manual' | 'carried_over' =
      state.pendingStroke.hit_zone_source === 'manual' ? 'manual' : 'carried_over'
    const cvOriginal = state.pendingStroke.hit_zone_cv ?? (autoHitZone as Zone9 | undefined) ?? null

    const stroke: StrokeInput = {
      stroke_num: state.currentStrokeNum,
      player: state.isDoubles ? state.currentHitter : state.currentPlayer,
      shot_type: state.pendingStroke.shot_type,
      hit_zone: finalHitZone,
      hit_zone_source: hitZoneSource,
      hit_zone_cv_original: cvOriginal,
      land_zone: undefined,
      is_backhand: state.pendingStroke.is_backhand,
      is_around_head: state.pendingStroke.is_around_head,
      above_net: state.pendingStroke.above_net,
      hit_height: state.pendingStroke.hit_height,
      timestamp_sec: state.pendingStroke.timestamp_sec,
    }

    // Phase C speed: flipMode に応じた次打者決定
    const willFlip = state.flipMode !== 'manual'
    const nextPlayer: 'player_a' | 'player_b' = willFlip
      ? (state.currentPlayer === 'player_a' ? 'player_b' : 'player_a')
      : state.currentPlayer

    set({
      currentStrokes: [...state.currentStrokes, stroke],
      undoStack: [...state.currentStrokes],
      currentStrokeNum: state.currentStrokeNum + 1,
      currentPlayer: nextPlayer,
      currentHitter: nextPlayer,  // 次チームの主プレイヤーにリセット
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      // Phase C speed: bounce revert 用に直前 player を覚える
      lastFlipAt: willFlip ? Date.now() : null,
      playerBeforeFlip: willFlip ? state.currentPlayer : null,
    })
  },

  // 打点の手動上書き
  selectHitZone: (zone) =>
    set((s) => ({ pendingStroke: { ...s.pendingStroke, hit_zone: zone } })),

  // Phase A: HitZoneSelector からのユーザ override
  // CV 値と一致するなら source='cv'、違うなら 'manual'
  setHitZoneOverride: (zone) =>
    set((s) => {
      // 旧実装は、押した値が先読み値と同じなら 'cv' に落としていた。
      // **人が押したという事実は、押した結果が何であっても変わらない。**
      // 一致したときだけ人間の確認が記録から消えるのは、来歴として誤り。
      const source = 'manual' as const
      return {
        pendingStroke: {
          ...s.pendingStroke,
          hit_zone: zone,
          hit_zone_source: source,
        },
      }
    }),

  // 属性トグル（ラリー中いつでも変更可能）
  toggleAttribute: (key) =>
    set((s) => ({
      pendingStroke: { ...s.pendingStroke, [key]: !s.pendingStroke[key] },
    })),

  setAboveNet: (v) =>
    set((s) => ({ pendingStroke: { ...s.pendingStroke, above_net: v } })),

  // 打球の高さ 4 段階（任意）。同じ値を再度渡すと解除（undefined）してトグル挙動にする。
  setHitHeight: (v) =>
    set((s) => ({
      pendingStroke: {
        ...s.pendingStroke,
        hit_height: s.pendingStroke.hit_height === v ? undefined : v,
      },
    })),

  // ネット上下サイクル: 未指定 → 上（true）→ 下（false）→ 未指定
  cycleAboveNet: () =>
    set((s) => {
      const cur = s.pendingStroke.above_net
      const next = cur === undefined ? true : cur === true ? false : undefined
      return { pendingStroke: { ...s.pendingStroke, above_net: next } }
    }),

  // プレイヤー切替（Tab）— チーム側を強制切替。ヒッターも主プレイヤーにリセット
  togglePlayer: () =>
    set((s) => {
      const next: 'player_a' | 'player_b' = s.currentPlayer === 'player_a' ? 'player_b' : 'player_a'
      return { currentPlayer: next, currentHitter: next }
    }),

  setPlayer: (p) => set({ currentPlayer: p, currentHitter: p }),

  // ダブルス制御
  setIsDoubles: (v) => set({ isDoubles: v }),
  // setHitter は currentPlayer も同期する（打者のチームが正しく反映されないバグ対策）
  // 旧: 文字列 suffix `_a` / `_b` で判定していたが、将来 hitter id に '_a' を含む
  // 名前 (例: '_anchor' 等) が混入すると壊れるため、explicit map で対応する。
  setHitter: (h) => {
    const team = HITTER_TO_TEAM[h] ?? 'player_a'  // 未知 hitter はデフォルトで player_a 側
    set({ currentHitter: h, currentPlayer: team })
  },
  toggleHitterWithinTeam: () =>
    set((s) => {
      if (!s.isDoubles) return {}
      const next =
        s.currentHitter === 'player_a' ? 'partner_a' :
        s.currentHitter === 'partner_a' ? 'player_a' :
        s.currentHitter === 'player_b' ? 'partner_b' : 'player_b'
      return { currentHitter: next }
    }),

  // ラリー確定: 勝者が次のサーバーになる（バドミントンラリーポイント制）
  confirmRally: (winner, _endType) => {
    const { currentStrokes, currentRallyNum, scoreA, scoreB } = get()
    const newScoreA = winner === 'player_a' ? scoreA + 1 : scoreA
    const newScoreB = winner === 'player_b' ? scoreB + 1 : scoreB

    // ダブルス: サーブ側が得点を続けたときは同じ選手が続けてサーブする（BWF ルール）。
    // 第1ストロークの打者がこのラリーのサーバ。サーブ権が移ったときの個人は
    // コート位置の記録が無いと決まらないので、従来どおり勝者チームの主選手に置き、
    // 打者は画面で選び直す。
    const rallyServer = currentStrokes[0]?.player
    const heldServe =
      get().isDoubles && rallyServer !== undefined && HITTER_TO_TEAM[rallyServer] === winner

    set({
      currentRallyNum: currentRallyNum + 1,
      scoreA: newScoreA,
      scoreB: newScoreB,
      isRallyActive: false,
      currentStrokes: [],
      undoStack: [],
      // #784: 解析モードの直近ラリー勝敗へ確定ラリーを追記する。
      recentRallyResults: [...get().recentRallyResults, { winner }],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      currentPlayer: winner,  // 勝者が次のサーバー（ラリーポイント制）
      currentHitter: heldServe && rallyServer ? rallyServer : winner,  // ダブルスで連続得点なら同じサーバ。それ以外は主選手
      // semi-auto bounce-revert 窓を次ラリーへ持ち越さない (持ち越すと次ラリー初手が
      // 500ms 以内のとき前ラリーの playerBeforeFlip で誤って server を上書きする)。
      lastFlipAt: null,
      playerBeforeFlip: null,
    })
    return currentStrokes
  },

  undoLastConfirmedRally: (snapshot) =>
    set((s) => ({
      scoreA: snapshot.scoreA,
      scoreB: snapshot.scoreB,
      currentRallyNum: snapshot.rallyNum,
      currentPlayer: snapshot.server,
      currentHitter: snapshot.server,
      // この確定で追記した 1 件だけを取り除く（空配列なら何もしない）。
      recentRallyResults: s.recentRallyResults.slice(0, -1),
      // 取り消し後は確定前のラリーを入力し直せるよう、入力途中の状態を捨てて idle に戻す。
      isRallyActive: false,
      currentStrokes: [],
      undoStack: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      lastFlipAt: null,
      playerBeforeFlip: null,
    })),

  resetRally: () =>
    set({
      isRallyActive: false,
      currentStrokes: [],
      undoStack: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      lastFlipAt: null,
      playerBeforeFlip: null,
      // currentPlayer は変えない（キャンセルなのでサーバーは同じ）
    }),

  // ペンディング中のストロークをキャンセル（確定済みストロークには触れない）
  cancelPendingStroke: () =>
    set({ inputStep: 'idle', pendingStroke: emptyPending() }),

  // アンドゥ（直前ストローク削除）
  undoLastStroke: () => {
    const { currentStrokes, currentStrokeNum } = get()
    if (currentStrokes.length === 0) return null
    const removedStroke = currentStrokes[currentStrokes.length - 1]
    const newStrokes = currentStrokes.slice(0, -1)
    // 削除したストロークの player から前チーム・前ヒッターを復元。
    // suffix 判定ではなく共有 HITTER_TO_TEAM マップで正確に解決する。
    const restoredHitter = removedStroke.player  // player_a/partner_a/player_b/partner_b
    const restoredPlayer: 'player_a' | 'player_b' = HITTER_TO_TEAM[restoredHitter] ?? 'player_a'
    set({
      currentStrokes: newStrokes,
      currentStrokeNum: Math.max(1, currentStrokeNum - 1),
      currentPlayer: restoredPlayer,
      currentHitter: restoredHitter,
      // 直前のショット種別をヒントとして残す（ショットパネルでハイライト表示）
      pendingStroke: { ...emptyPending(), shot_type: removedStroke.shot_type },
      inputStep: 'idle',
    })
    return removedStroke
  },

  nextSet: (setId, setNum) =>
    set((s) => ({
      currentSetId: setId,
      currentSetNum: setNum,
      scoreA: 0,
      scoreB: 0,
      currentRallyNum: 1,
      isRallyActive: false,
      currentStrokes: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      // currentPlayer はセット最終ラリーの勝者を引き継ぐ（バドミントンルール）
      currentHitter: s.currentPlayer,  // ダブルス: セット開始時は主プレイヤーにリセット
    })),

  // Phase C speed: flipMode 設定 (localStorage 永続化)
  setFlipMode: (mode) => {
    if (typeof window !== 'undefined') {
      try { window.localStorage.setItem(FLIP_MODE_KEY, mode) } catch { /* noop */ }
    }
    set({ flipMode: mode, lastFlipAt: null, playerBeforeFlip: null })
  },

  // 見逃しラリー: スコア更新 + サーバー更新（ストロークなし）
  skipRallyState: (winner) => {
    const { currentRallyNum, scoreA, scoreB } = get()
    set({
      currentRallyNum: currentRallyNum + 1,
      scoreA: winner === 'player_a' ? scoreA + 1 : scoreA,
      scoreB: winner === 'player_b' ? scoreB + 1 : scoreB,
      currentPlayer: winner,  // 勝者が次のサーバー
      currentHitter: winner,  // ダブルス: 勝者チームの主プレイヤーにリセット
      // #784: 見逃しラリー（ストロークなし得点）も直近ラリー勝敗へ反映する。
      recentRallyResults: [...get().recentRallyResults, { winner }],
    })
  },

  // スコア補正: 外部でAPIを保存した後に呼ぶ
  applyScoreCorrection: (scoreA, scoreB, rallyNum) =>
    set({ scoreA, scoreB, currentRallyNum: rallyNum }),

  // G2+移動系: 直前確定ストロークのエンリッチメント更新（落点確定直後のオプション入力）
  // F-T003-01: 実体は updateStrokeEnrichmentAt に委譲。既定の «直前» 挙動は維持する。
  updateLastStrokeEnrichment: (fields) => {
    const { currentStrokes } = get()
    if (currentStrokes.length === 0) return
    get().updateStrokeEnrichmentAt(currentStrokes.length - 1, fields)
  },

  // F-T003-01: index 指定のエンリッチメント更新。詳細分析パネルから
  // «直前以外» のストロークも後から補完できるようにする共通実装。
  updateStrokeEnrichmentAt: (index, { returnQuality, contactHeight, contactZone, movementBurden, movementDirection, intentTag, intentNote }) => {
    const { currentStrokes } = get()
    // 範囲外 index は無視 (壊れた入力でストローク配列を汚さない)。
    if (index < 0 || index >= currentStrokes.length) return
    const updated = [...currentStrokes]
    const target = { ...updated[index] }
    if (returnQuality !== undefined) target.return_quality = returnQuality
    if (contactHeight !== undefined) target.contact_height = contactHeight
    if (contactZone !== undefined) target.contact_zone = contactZone
    if (movementBurden !== undefined) target.movement_burden = movementBurden
    if (movementDirection !== undefined) target.movement_direction = movementDirection
    if (intentTag !== undefined) target.intent_tag = intentTag
    if (intentNote !== undefined) target.intent_note = intentNote
    updated[index] = target
    set({ currentStrokes: updated })
  },
}))

/**
 * ストアが現在の URL の試合のものか。ラリー保存の直前に確認し、
 * 前の試合の setId / スコアを現在の試合に書き込まないための最終防御 (A-11)。
 */
export function isStoreForMatch(storeMatchId: number | null, routeMatchId: string | number | undefined): boolean {
  if (storeMatchId == null || routeMatchId == null || routeMatchId === '') return false
  return storeMatchId === Number(routeMatchId)
}
