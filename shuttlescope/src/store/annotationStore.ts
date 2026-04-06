import { create } from 'zustand'
import { ShotType, StrokeInput, Zone9 } from '@/types'

export type InputStep =
  | 'idle'        // 待機中（Space/ショットキーでラリー開始）
  | 'land_zone'   // 着地ゾーン選択待ち（ショット入力直後）
  | 'rally_end'   // ラリー終了確認中

export interface PendingStroke {
  shot_type?: ShotType
  hit_zone?: Zone9
  land_zone?: Zone9
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
  currentPlayer: 'player_a' | 'player_b'  // 現在打球するプレイヤー

  // アンドゥ（最大10件）
  undoStack: StrokeInput[]

  // K-002: 保存キュー状態
  pendingSaveCount: number
  saveErrors: SaveError[]

  // アクション
  init: (matchId: number, setId: number, setNum: number, rallyNum: number, scoreA: number, scoreB: number) => void
  setCurrentSet: (setId: number, setNum: number) => void
  // K-002: 保存キュー操作
  incrementPending: () => void
  decrementPending: () => void
  addSaveError: (err: SaveError) => void
  clearSaveErrors: () => void

  // ラリー操作
  startRally: (timestamp: number) => void
  endRallyRequest: () => void   // ラリー終了確認画面へ
  cancelRallyEnd: () => void

  // ストローク入力（2アクション：ショットキー → 着地クリック）
  inputShotType: (shotType: ShotType, timestamp: number) => void  // ショットキー押下
  selectLandZone: (zone: Zone9) => void  // 着地クリック → 自動確定
  selectHitZone: (zone: Zone9) => void   // 打点（任意で上書き）
  toggleAttribute: (key: 'is_backhand' | 'is_around_head') => void
  setAboveNet: (v: boolean | undefined) => void

  // プレイヤー制御
  togglePlayer: () => void
  setPlayer: (p: 'player_a' | 'player_b') => void

  // ラリー確定（DB保存はページ側で実行）
  confirmRally: (winner: 'player_a' | 'player_b', endType: string) => StrokeInput[]
  resetRally: () => void

  // アンドゥ
  undoLastStroke: () => void

  // スコア更新（デュース含む）
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

  init: (matchId, setId, setNum, rallyNum, scoreA, scoreB) =>
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
      currentPlayer: 'player_a',
      undoStack: [],
      pendingSaveCount: 0,
      saveErrors: [],
    }),

  setCurrentSet: (setId, setNum) =>
    set({ currentSetId: setId, currentSetNum: setNum }),

  // ラリー開始
  startRally: (timestamp) =>
    set({
      isRallyActive: true,
      rallyStartTimestamp: timestamp,
      currentStrokes: [],
      undoStack: [],
      currentStrokeNum: 1,
      currentPlayer: 'player_a',
      pendingStroke: emptyPending(),
      inputStep: 'idle',
    }),

  // ラリー終了確認へ
  endRallyRequest: () => set({ inputStep: 'rally_end' }),
  cancelRallyEnd: () => set({ inputStep: 'idle' }),

  // ① ショットキー押下（ラリー中でなければ自動起動）
  inputShotType: (shotType, timestamp) => {
    const { isRallyActive, currentStrokes, pendingStroke } = get()

    // ラリー未開始なら自動起動
    if (!isRallyActive) {
      set({
        isRallyActive: true,
        rallyStartTimestamp: timestamp,
        currentStrokes: [],
        undoStack: [],
        currentStrokeNum: 1,
        currentPlayer: 'player_a',
      })
    }

    // cant_reach は着地ゾーン不要 → 即確定
    if (shotType === 'cant_reach') {
      const state = get()
      const stroke: StrokeInput = {
        stroke_num: state.currentStrokeNum,
        player: state.currentPlayer,
        shot_type: 'cant_reach',
        hit_zone: state.pendingStroke.hit_zone,
        land_zone: undefined,
        is_backhand: state.pendingStroke.is_backhand,
        is_around_head: state.pendingStroke.is_around_head,
        above_net: state.pendingStroke.above_net,
        timestamp_sec: timestamp,
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
      return
    }

    // 通常: ショット入力後に着地ゾーン待ち
    set((s) => ({
      pendingStroke: {
        ...s.pendingStroke,
        shot_type: shotType,
        timestamp_sec: timestamp,
      },
      inputStep: 'land_zone',
    }))
  },

  // ② 着地ゾーン選択 → ストローク自動確定
  selectLandZone: (zone) => {
    const state = get()
    if (!state.pendingStroke.shot_type) return

    // 直前ストロークの着地ゾーンを今回の打点として自動セット
    const prevStroke = state.currentStrokes[state.currentStrokes.length - 1]
    const autoHitZone = prevStroke?.land_zone ?? state.pendingStroke.hit_zone

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

  // 属性トグル（いつでも変更可能）
  toggleAttribute: (key) =>
    set((s) => ({
      pendingStroke: { ...s.pendingStroke, [key]: !s.pendingStroke[key] },
    })),

  setAboveNet: (v) =>
    set((s) => ({ pendingStroke: { ...s.pendingStroke, above_net: v } })),

  // プレイヤー切替（Tab）
  togglePlayer: () =>
    set((s) => ({
      currentPlayer: s.currentPlayer === 'player_a' ? 'player_b' : 'player_a',
    })),

  setPlayer: (p) => set({ currentPlayer: p }),

  // ラリー確定（ストロークリストを返してDB保存はページ側）
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
      currentPlayer: 'player_a',
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
    }),

  // アンドゥ（直前ストローク削除）
  undoLastStroke: () => {
    const { currentStrokes, currentStrokeNum, currentPlayer, undoStack } = get()
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
    }),
}))
