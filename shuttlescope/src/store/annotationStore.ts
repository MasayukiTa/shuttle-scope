import { create } from 'zustand'
import { ShotType, StrokeInput, Zone9, LandZone, ZoneNet } from '@/types'

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
  hit_zone_source?: 'cv' | 'manual'
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
  currentPlayer: 'player_a' | 'player_b'  // 現在打球するチーム側（= 次ラリーのサーバー）
  isDoubles: boolean                        // ダブルスモード
  currentHitter: string                     // 実際の打者: player_a | partner_a | player_b | partner_b

  // アンドゥ（最大10件）
  undoStack: StrokeInput[]

  // K-002: 保存キュー状態
  pendingSaveCount: number
  saveErrors: SaveError[]

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
  // Phase A: 打点を人間が override (HitZoneSelector からのタップ)
  setHitZoneOverride: (zone: Zone9) => void
  toggleAttribute: (key: 'is_backhand' | 'is_around_head') => void
  setAboveNet: (v: boolean | undefined) => void
  cycleAboveNet: () => void              // ネット上下サイクル（未指定→上→下→未指定）

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
  }) => void

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
  isDoubles: false,
  currentHitter: 'player_a',
  undoStack: [],
  pendingSaveCount: 0,
  saveErrors: [],
  flipMode: loadFlipMode(),
  lastFlipAt: null,
  playerBeforeFlip: null,

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
      currentHitter: initialServer ?? 'player_a',
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
        hit_zone_source: 'cv',
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
    // それ以外（CV値そのまま or autoHitZone 由来）は 'cv' 扱い。
    const finalHitZone = state.pendingStroke.hit_zone_source === 'manual'
      ? state.pendingStroke.hit_zone
      : autoHitZone
    const hitZoneSource: 'cv' | 'manual' =
      state.pendingStroke.hit_zone_source === 'manual' ? 'manual' : 'cv'
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
    const autoHitZone = prevStroke?.land_zone ?? state.pendingStroke.hit_zone

    const finalHitZone = state.pendingStroke.hit_zone_source === 'manual'
      ? (state.pendingStroke.hit_zone as Zone9 | undefined)
      : (autoHitZone as Zone9 | undefined)
    const hitZoneSource: 'cv' | 'manual' =
      state.pendingStroke.hit_zone_source === 'manual' ? 'manual' : 'cv'
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
      const cv = s.pendingStroke.hit_zone_cv ?? null
      const source: 'cv' | 'manual' = (cv != null && zone === cv) ? 'cv' : 'manual'
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
  setHitter: (h) => set({
    currentHitter: h,
    currentPlayer: (h === 'player_b' || h === 'partner_b') ? 'player_b' : 'player_a',
  }),
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
      currentHitter: winner,  // ダブルス: 勝者チームの主プレイヤーにリセット
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
    const { currentStrokes, currentStrokeNum } = get()
    if (currentStrokes.length === 0) return null
    const removedStroke = currentStrokes[currentStrokes.length - 1]
    const newStrokes = currentStrokes.slice(0, -1)
    // 削除したストロークの player から前チーム・前ヒッターを復元
    const restoredHitter = removedStroke.player  // player_a/partner_a/player_b/partner_b
    const restoredPlayer: 'player_a' | 'player_b' =
      restoredHitter.includes('_a') ? 'player_a' : 'player_b'
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
    })
  },

  // スコア補正: 外部でAPIを保存した後に呼ぶ
  applyScoreCorrection: (scoreA, scoreB, rallyNum) =>
    set({ scoreA, scoreB, currentRallyNum: rallyNum }),

  // G2+移動系: 直前確定ストロークのエンリッチメント更新（落点確定直後のオプション入力）
  updateLastStrokeEnrichment: ({ returnQuality, contactHeight, contactZone, movementBurden, movementDirection }) => {
    const { currentStrokes } = get()
    if (currentStrokes.length === 0) return
    const updated = [...currentStrokes]
    const last = { ...updated[updated.length - 1] }
    if (returnQuality !== undefined) last.return_quality = returnQuality
    if (contactHeight !== undefined) last.contact_height = contactHeight
    if (contactZone !== undefined) last.contact_zone = contactZone
    if (movementBurden !== undefined) last.movement_burden = movementBurden
    if (movementDirection !== undefined) last.movement_direction = movementDirection
    updated[updated.length - 1] = last
    set({ currentStrokes: updated })
  },
}))
