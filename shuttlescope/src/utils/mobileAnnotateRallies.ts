/**
 * ラリー入力まわりの純粋ロジック (LiveInputPage / MobileAnnotatePage 共用)。
 *
 * ここに集める理由: 「サーバのラリー」と「端末内の未送信ラリー」の同一性、
 * 次のサーバ、再入場時の開始位置は、画面ごとに書くと食い違う。
 * 判定を 1 か所に置き、画面は結果を表示するだけにする。
 */

export type Side = 'player_a' | 'player_b'

export interface RallyKeyed {
  id?: number | null
  client_uuid?: string
  set_id: number
  rally_num: number
}

/**
 * ラリーの同一性は (set_id, rally_num)。バックエンドは同じ組を一意にしており
 * (POST /rallies は既存行をそのまま返す)、サーバが採番する rally.uuid は
 * 送信キューの clientUuid (冪等キー) とは別の値なので、uuid では突き合わせられない。
 */
export function rallyKey(r: Pick<RallyKeyed, 'set_id' | 'rally_num'>): string {
  return `${r.set_id}:${r.rally_num}`
}

/**
 * サーバのラリーと端末内の未送信ラリーを 1 つの一覧にする。
 * 同じラリーが両方にあればサーバ側を採る。端末内の重複 (二度押し) も 1 件にする。
 */
export function mergeRallies<T extends RallyKeyed>(server: T[], local: T[]): T[] {
  const seen = new Set<string>()
  const serverUuids = new Set<string>()
  const out: T[] = []
  for (const r of server) {
    const k = rallyKey(r)
    if (seen.has(k)) continue
    seen.add(k)
    if (r.client_uuid) serverUuids.add(r.client_uuid)
    out.push(r)
  }
  for (const r of local) {
    const k = rallyKey(r)
    if (seen.has(k)) continue
    if (r.client_uuid && serverUuids.has(r.client_uuid)) continue
    seen.add(k)
    out.push(r)
  }
  return out.sort((a, b) => (a.set_id !== b.set_id ? a.set_id - b.set_id : a.rally_num - b.rally_num))
}

/** サーバに反映済みの未送信ラリーを取り除く (送信成功の反映)。変化が無ければ同じ配列を返す。 */
export function pruneConfirmed<T extends RallyKeyed>(server: T[], local: T[]): T[] {
  if (local.length === 0) return local
  const keys = new Set(server.map(rallyKey))
  const next = local.filter((r) => !keys.has(rallyKey(r)))
  return next.length === local.length ? local : next
}

interface SetLike {
  id: number
  set_num: number
}

/**
 * 現在のセットの最初のラリーのサーバ。
 * 1) 同じセットに既存ラリーがあれば、最後のラリーの勝者
 * 2) 無ければ直前のセット (ラリーのあるもの) の最後のラリーの勝者
 * 3) 無ければ試合の initial_server
 * どれも無ければ null (呼び出し側が入力者に選ばせる。player_a を仮定しない)。
 */
export function resolveNextServer(args: {
  rallies: Array<Pick<RallyKeyed, 'set_id' | 'rally_num'> & { winner: Side }>
  sets: SetLike[]
  currentSetId: number
  matchInitialServer?: string | null
}): Side | null {
  const { rallies, sets, currentSetId, matchInitialServer } = args
  const lastOf = (setId: number) => {
    let best: (typeof rallies)[number] | null = null
    for (const r of rallies) {
      if (r.set_id !== setId) continue
      if (!best || r.rally_num > best.rally_num) best = r
    }
    return best
  }
  const own = lastOf(currentSetId)
  if (own) return own.winner
  const cur = sets.find((s) => s.id === currentSetId)
  if (cur) {
    const earlier = sets.filter((s) => s.set_num < cur.set_num).sort((a, b) => b.set_num - a.set_num)
    for (const s of earlier) {
      const last = lastOf(s.id)
      if (last) return last.winner
    }
  }
  return matchInitialServer === 'player_a' || matchInitialServer === 'player_b' ? matchInitialServer : null
}

export type FinalShotOutcome = 'winner_shot' | 'opponent_error'

/** 最後に打った人。勝者の決定打なら勝者、相手のミスなら敗者 (勝者から推定しない)。 */
export function finalHitterFor(rally: { winner: Side }, outcome: FinalShotOutcome): Side {
  if (outcome === 'winner_shot') return rally.winner
  return rally.winner === 'player_a' ? 'player_b' : 'player_a'
}

export type CancelResult = 'cancelled' | 'inflight' | 'not_found'
export type UndoPendingAction = 'remove_local' | 'keep_busy' | 'enqueue_delete'

/**
 * 未送信ラリーの取消結果から、次にやることを決める。
 * - 送信前に取消せた: 画面から消すだけ
 * - 送信中: 結果が分からないので画面に残し、あとで再操作させる
 * - キューに無い (送信済み): サーバ側の行があれば削除を送る。無ければ画面から消す
 */
export function decideUndoPending(result: CancelResult, serverRallyId: number | null): UndoPendingAction {
  if (result === 'cancelled') return 'remove_local'
  if (result === 'inflight') return 'keep_busy'
  return serverRallyId != null ? 'enqueue_delete' : 'remove_local'
}

export interface AnnotationStateLite {
  current_set_num: number
  current_rally_num: number
  score_a: number
  score_b: number
  next_server?: Side | null
}

export interface LiveStartPlan {
  setNum: number
  /** 既存セット。null なら呼び出し側が作成する */
  set: SetLike | null
  rallyNum: number
  scoreA: number
  scoreB: number
  server: Side | null
}

/**
 * /live 再入場時の開始位置。サーバの状態 (最後のラリーの次) を唯一の根拠にする。
 * セットは配列の末尾ではなく set_num で探す (並び順に依存しない)。
 */
export function planLiveStart(state: AnnotationStateLite, sets: SetLike[]): LiveStartPlan {
  const set = sets.find((s) => s.set_num === state.current_set_num) ?? null
  return {
    setNum: state.current_set_num,
    set,
    rallyNum: state.current_rally_num,
    scoreA: state.score_a,
    scoreB: state.score_b,
    server: state.next_server === 'player_a' || state.next_server === 'player_b' ? state.next_server : null,
  }
}

/** 画面に残っている状態を捨てて良いか。未保存・保存失敗があるときはサーバより画面が正しい。 */
export function shouldReinitFromServer(store: {
  matchId: number | null
  currentSetId: number | null
  pendingSaveCount: number
  saveErrorCount: number
}, matchId: number, setId: number): boolean {
  const same = store.matchId === matchId && store.currentSetId === setId
  if (!same) return true
  return store.pendingSaveCount === 0 && store.saveErrorCount === 0
}

export interface StrokeKeyed {
  id?: number | null
  rally_id: number
  stroke_num: number
}

/** ストロークの同一性は (rally_id, stroke_num)。サーバ採番の id は未送信の端末内 stroke には無い。 */
export function strokeKey(s: Pick<StrokeKeyed, 'rally_id' | 'stroke_num'>): string {
  return `${s.rally_id}:${s.stroke_num}`
}

/**
 * 編集済みの値 (id 単位) をサーバ由来のストロークへ重ねる。
 * 編集は送信キューへ積むだけで再取得されないため、画面側の表示を最新にするのに使う。
 */
export function applyStrokeOverrides<T extends StrokeKeyed>(
  server: T[],
  overrides: ReadonlyMap<number, Partial<T>>,
): T[] {
  if (overrides.size === 0) return server
  return server.map((s) => {
    const patch = s.id != null ? overrides.get(s.id) : undefined
    return patch ? { ...s, ...patch } : s
  })
}

/**
 * サーバのストロークと端末内の未送信ストロークを 1 つの一覧にする。
 * 送信済みで再取得後にサーバ側へ現れた stroke は、端末内の同一 (rally_id, stroke_num) を捨てて二重表示を防ぐ。
 */
export function mergeStrokes<T extends StrokeKeyed>(server: T[], local: T[]): T[] {
  const seen = new Set(server.map(strokeKey))
  const out = [...server]
  for (const s of local) {
    const k = strokeKey(s)
    if (seen.has(k)) continue
    seen.add(k)
    out.push(s)
  }
  return out
}
