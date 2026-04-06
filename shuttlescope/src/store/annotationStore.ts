import { create } from 'zustand'
import { ShotType, StrokeInput, Zone9, LandZone, ZoneNet } from '@/types'

export type InputStep =
  | 'idle'        // 待機中（ショットキーでラリー開始）
  | 'land_zone'   // 落点選択待ち（ショット入力直後）
  | 'rally_end'   // ラリー終了確認中

export interface PendingStroke {
  shot_type?: ShotType
  hit_zone?: Zone9
  land_zone?: LandZone
  is_backhand: boolean
  is_around_head: boolean
  above_net?: boolean
  timestamp_sec?: number
}

// K-002: 保存キュー
export interface SaveError {
  rallyNum: number
  error: string
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
  currentPlayer: 'player_a' | 'player_b'  // 現在打球するプレイヤー（= 次ラリーのサーバー）

  // アンドゥ（最大10件）
  undoStack: StrokeInput[]

  // K-002: 保存キュー状態
  pendingSaveCount: number
  saveErrors: SaveError[]

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
  // K-002: 保存キュー操作
  incrementPending: () => void
  decrementPending: () => void
  addSaveError: (err: SaveError) => void
  clearSaveErrors: () => void

  // ラリー操作
  startRally: (timestamp: number) => void
  endRallyRequest: () => void
  cancelRallyEnd: () => void

  // ストローク入力（2アクション：ショットキー → 落点入力）
  inputShotType: (shotType: ShotType, timestamp: number) => void
  selectLandZone: (zone: LandZone) => void  // 落点クリック or テンキー → 自動確定
  skipLandZone: () => void                // 落点スキップ（0キー / Numpad0）→ 自動確定
  selectHitZone: (zone: Zone9) => void    // 打点（任意で上書き）
  toggleAttribute: (key: 'is_backhand' | 'is_around_head') => void
  setAboveNet: (v: boolean | undefined) => void
  cycleAboveNet: () => void              // ネット上下サイクル（未指定→上→下→未指定）

  // プレイヤー制御
  togglePlayer: () => void
  setPlayer: (p: 'player_a' | 'player_b') => void

  // ラリー確定（DB保存はページ側で実行）
  confirmRally: (winner: 'player_a' | 'player_b', endType: string) => StrokeInput[]
  resetRally: () => void

  // 見逃しラリー（ストロークなしで得点だけ記録）
  skipRallyState: (winner: 'player_a' | 'player_b') => void
  // スコア補正（スコア・ラリー番号を直接更新。API保存はページ側で行う）
  applyScoreCorrection: (scoreA: number, scoreB: number, rallyNum: number) => void

  // アンドゥ
  undoLastStroke: () => void

  // ペンディング中のストロークをキャンセル（落点待ち中にEsc/Backspace/Ctrl+Z）
  cancelPendingStroke: () => void

  // セット移行
  nextSet: (setId: number, setNum: number) => void
}

const emptyPending = (): PendingStroke => ({
  is_backhand: false,
  is_around_head: false,
  above_net: undefined,
})

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
  undoStack: [],
  pendingSaveCount: 0,
  saveErrors: [],

  // K-002: 保存キュー操作
  incrementPending: () => set((s) => ({ pendingSaveCount: s.pendingSaveCount + 1 })),
  decrementPending: () => set((s) => ({ pendingSaveCount: Math.max(0, s.pendingSaveCount - 1) })),
  addSaveError: (err) => set((s) => ({ saveErrors: [...s.saveErrors, err] })),
  clearSaveErrors: () => set({ saveErrors: [] }),

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
      // 最初のラリーのみ initial_server を使用。それ以降は confirmRally が維持する
      currentPlayer: initialServer ?? 'player_a',
      undoStack: [],
      pendingSaveCount: 0,
      saveErrors: [],
    }),

  setCurrentSet: (setId, setNum) =>
    set({ currentSetId: setId, currentSetNum: setNum }),

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

    // 通常: ショット入力後に落点待ち
    set((s) => ({
      pendingStroke: {
        ...s.pendingStroke,
        shot_type: shotType,
        timestamp_sec: timestamp,
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

    const stroke: StrokeInput = {
      stroke_num: state.currentStrokeNum,
      player: state.currentPlayer,
      shot_type: state.pendingStroke.shot_type,
      hit_zone: autoHitZone,
      land_zone: zone,
      is_backhand: state.pendingStroke.is_backhand,
      is_around_head: state.pendingStroke.is_around_head,
      above_net: state.pendingStroke.above_net,
      timestamp_sec: state.pendingStroke.timestamp_sec,
    }

    const nextPlayer: 'player_a' | 'player_b' =
      state.currentPlayer === 'player_a' ? 'player_b' : 'player_a'

    const isOOB = String(zone).startsWith('OB_')
    const isNet = (NET_ZONES as string[]).includes(zone)

    set({
      currentStrokes: [...state.currentStrokes, stroke],
      undoStack: [...state.currentStrokes],
      currentStrokeNum: state.currentStrokeNum + 1,
      currentPlayer: nextPlayer,
      pendingStroke: emptyPending(),
      // OOB/NETならそのままrally_end（ラリー終了確定）
      inputStep: isOOB || isNet ? 'rally_end' : 'idle',
    })
  },

  // ② 落点スキップ（アウト・ネット時など） → land_zone なしで確定
  skipLandZone: () => {
    const state = get()
    if (!state.pendingStroke.shot_type) return

    const prevStroke = state.currentStrokes[state.currentStrokes.length - 1]
    const autoHitZone = prevStroke?.land_zone ?? state.pendingStroke.hit_zone

    const stroke: StrokeInput = {
      stroke_num: state.currentStrokeNum,
      player: state.currentPlayer,
      shot_type: state.pendingStroke.shot_type,
      hit_zone: autoHitZone,
      land_zone: undefined,
      is_backhand: state.pendingStroke.is_backhand,
      is_around_head: state.pendingStroke.is_around_head,
      above_net: state.pendingStroke.above_net,
      timestamp_sec: state.pendingStroke.timestamp_sec,
    }

    const nextPlayer: 'player_a' | 'player_b' =
      state.currentPlayer === 'player_a' ? 'player_b' : 'player_a'

    set({
      currentStrokes: [...state.currentStrokes, stroke],
      undoStack: [...state.currentStrokes],
      currentStrokeNum: state.currentStrokeNum + 1,
      currentPlayer: nextPlayer,
      pendingStroke: emptyPending(),
      inputStep: 'idle',
    })
  },

  // 打点の手動上書き
  selectHitZone: (zone) =>
    set((s) => ({ pendingStroke: { ...s.pendingStroke, hit_zone: zone } })),

  // 属性トグル（ラリー中いつでも変更可能）
  toggleAttribute: (key) =>
    set((s) => ({
      pendingStroke: { ...s.pendingStroke, [key]: !s.pendingStroke[key] },
    })),

  setAboveNet: (v) =>
    set((s) => ({ pendingStroke: { ...s.pendingStroke, above_net: v } })),

  // ネット上下サイクル: 未指定 → 上（true）→ 下（false）→ 未指定
  cycleAboveNet: () =>
    set((s) => {
      const cur = s.pendingStroke.above_net
      const next = cur === undefined ? true : cur === true ? false : undefined
      return { pendingStroke: { ...s.pendingStroke, above_net: next } }
    }),

  // プレイヤー切替（Tab）
  togglePlayer: () =>
    set((s) => ({
      currentPlayer: s.currentPlayer === 'player_a' ? 'player_b' : 'player_a',
    })),

  setPlayer: (p) => set({ currentPlayer: p }),

  // ラリー確定: 勝者が次のサーバーになる（バドミントンラリーポイント制）
  confirmRally: (winner, endType) => {
    const { currentStrokes, currentRallyNum, scoreA, scoreB } = get()
    const newScoreA = winner === 'player_a' ? scoreA + 1 : scoreA
    const newScoreB = winner === 'player_b' ? scoreB + 1 : scoreB

    set({
      currentRallyNum: currentRallyNum + 1,
      scoreA: newScoreA,
      scoreB: newScoreB,
      isRallyActive: false,
      currentStrokes: [],
      undoStack: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      currentPlayer: winner,  // 勝者が次のサーバー（ラリーポイント制）
    })
    return currentStrokes
  },

  resetRally: () =>
    set({
      isRallyActive: false,
      currentStrokes: [],
      undoStack: [],
      pendingStroke: emptyPending(),
      inputStep: 'idle',
      currentStrokeNum: 1,
      // currentPlayer は変えない（キャンセルなのでサーバーは同じ）
    }),

  // ペンディング中のストロークをキャンセル（確定済みストロークには触れない）
  cancelPendingStroke: () =>
    set({ inputStep: 'idle', pendingStroke: emptyPending() }),

  // アンドゥ（直前ストローク削除）
  undoLastStroke: () => {
    const { currentStrokes, currentStrokeNum, currentPlayer } = get()
    if (currentStrokes.length === 0) return
    const newStrokes = currentStrokes.slice(0, -1)
    const prevPlayer: 'player_a' | 'player_b' =
      currentPlayer === 'player_a' ? 'player_b' : 'player_a'
    set({
      currentStrokes: newStrokes,
      currentStrokeNum: Math.max(1, currentStrokeNum - 1),
      currentPlayer: prevPlayer,
      pendingStroke: emptyPending(),
      inputStep: 'idle',
    })
  },

  nextSet: (setId, setNum) =>
    set({
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
    }),

  // 見逃しラリー: スコア更新 + サーバー更新（ストロークなし）
  skipRallyState: (winner) => {
    const { currentRallyNum, scoreA, scoreB } = get()
    set({
      currentRallyNum: currentRallyNum + 1,
      scoreA: winner === 'player_a' ? scoreA + 1 : scoreA,
      scoreB: winner === 'player_b' ? scoreB + 1 : scoreB,
      currentPlayer: winner,  // 勝者が次のサーバー
    })
  },

  // スコア補正: 外部でAPIを保存した後に呼ぶ
  applyScoreCorrection: (scoreA, scoreB, rallyNum) =>
    set({ scoreA, scoreB, currentRallyNum: rallyNum }),
}))
