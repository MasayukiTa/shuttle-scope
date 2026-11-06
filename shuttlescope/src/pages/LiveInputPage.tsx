/**
 * LiveInputPage — Phase C 試合中専用フルブリード入力ページ (MVP scaffold)
 *
 * 目的:
 *   試合中はノート PC を開かず iPhone / iPad だけで素早くスコア + ストロークを
 *   記録するための専用 UI。AnnotatorPage はデスクトップ向けに大量の機能を抱えて
 *   いるが、LiveInputPage は試合進行を止めない最小操作に絞る。
 *
 * MVP の scope:
 *   - ルート `/live/:matchId`
 *   - フルブリード (サイドバー / ボトムナビ非表示) を `body[data-live-mode]` で制御
 *   - 2 モードトグル: RALLY (ストローク入力) / RESULT (得点者・終了種別)
 *   - 既存 useAnnotationStore + saveRally 経路を再利用 (DB スキーマ変更ゼロ)
 *   - ShotTypePanel / RallyPanel / AttributePanel を mobile-first に再配置
 *
 * 今回 scope 外 (TODO):
 *   - キーボード操作完全対応 (現状は AnnotatorPage の useKeyboard が前提)
 *   - 動画プレビューと一時停止連動
 *   - オフライン同期 (useOfflineSync)
 *   - ダブルス 4-quad 打者選択 (AnnotatorPage 版を import 移行する)
 *   - L-Audio: スコアコール時の音声フィードバック (Phase C 全体計画)
 *
 * これらは AnnotatorPage 側に既に実装済なので、必要になったら参照して移植する。
 */
import { useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'
import { ShotTypePanel } from '@/components/annotation/ShotTypePanel'
import { AttributePanel } from '@/components/annotation/AttributePanel'
import { RallyPanel } from '@/components/annotation/RallyPanel'
import { useAnnotationStore, type ConfirmedRallySnapshot } from '@/store/annotationStore'
import { buildBatchPayload, buildSkippedRallyPayload } from '@/utils/annotationPayload'
import { apiPost, apiPut, apiDelete, newIdempotencyKey } from '@/api/client'
import { setWinner, isMatchDecidedBySet } from '@/utils/badmintonRules'
import { useAuth } from '@/hooks/useAuth'
import { useOfflineSync } from '@/hooks/useOfflineSync'
import { errorMessage } from '@/utils/errors'
import { QueryErrorNotice } from '@/components/common/QueryErrorNotice'
import { isSetEndBlockedBySave, loadQueuedRallyCount, classifyConfirmSaveFailure } from '@/utils/liveSetEndGuard'
import {
  offlineStrokeIdempotencyKey,
  removeRallyAfterSave,
  stashRallyBeforeSave,
} from '@/utils/offlineStrokeQueue'
import {
  planLiveStart,
  shouldReinitFromServer,
  type AnnotationStateLite,
  type Side,
} from '@/utils/mobileAnnotateRallies'
import type { Match, ShotType } from '@/types'

type LiveMode = 'rally' | 'result'

export function LiveInputPage() {
  const { matchId: matchIdStr } = useParams<{ matchId: string }>()
  const matchId = matchIdStr ? parseInt(matchIdStr, 10) : null
  const navigate = useNavigate()
  const { t } = useTranslation()

  const [mode, setMode] = useState<LiveMode>('rally')

  // #664: 直前に確定した得点を取り消すための導線。ワンタップ即保存のため、確定直後に
  // 誤タップへ気づいたとき、ローカル状態を確定前へ戻し、保存済みなら server 側の
  // ラリーも削除する。snapshot は confirmRally が strokes を捨てる前に capture する。
  // rallyId は /strokes/batch 成功時に確定する (保存前は null)。
  const [lastConfirmed, setLastConfirmed] = useState<null | {
    snapshot: ConfirmedRallySnapshot
    winner: 'player_a' | 'player_b'
    endType: string
    rallyId: number | null  // null = まだ保存前 / 保存されなかった (スキップ送信中)
    saving: boolean         // batch 保存の完了待ち
    saveFailed: boolean     // 恒久的な保存失敗 (冪等キーで送り直しても直らない 4xx)。
    // 一過性の失敗 (タイムアウト・通信断・5xx 等)。サーバは保存済みのことがあり、
    // 退避キューに残して useOfflineSync が同じ冪等キーで自動再送する。「失敗」ではなく
    // 「再送待ち」として扱い、赤い保存失敗表示は出さない。
    pendingResend: boolean
    undoing: boolean        // server 削除の進行中
    undoError: string | null
  }>(null)

  const store = useAnnotationStore()

  // フルブリード化: body に data-live-mode を貼り、App.tsx 側のサイドバー/ボトムナビが
  // CSS で非表示になる。AnnotatorPage の isAnnotatorPage 判定と同等の経路。
  useEffect(() => {
    document.body.setAttribute('data-live-mode', '1')
    return () => {
      document.body.removeAttribute('data-live-mode')
    }
  }, [])

  // match + 既存の最新 set 取得 (簡易)
  const { data: matchData, isError: matchError, refetch: refetchMatch } = useQuery<{ data: Match }>({
    queryKey: ['live-match', matchId],
    queryFn: () => apiGet(`/matches/${matchId}`),
    enabled: !!matchId,
    staleTime: 60_000,
  })

  const match = matchData?.data

  // 再入場時の開始位置 (ラリー番号・得点・サーバー・セット) は、サーバの
  // /annotation/{id}/state だけを根拠にする。固定の初期値で store.init() しない。
  // セットは配列の末尾ではなく set_num で探す (API の並び順に依存しない)。
  const [liveSet, setLiveSet] = useState<{ id: number; set_num: number } | null>(null)
  const [initError, setInitError] = useState<string | null>(null)
  const [initNonce, setInitNonce] = useState(0)
  // サーバ側に先サーブの情報が無いとき、入力者に選ばせる
  const [needServer, setNeedServer] = useState<null | { setId: number; setNum: number; rallyNum: number; scoreA: number; scoreB: number }>(null)
  // セット終了 → 次セット (または試合終了) の処理状態
  const [setEndState, setSetEndState] = useState<{ busy: boolean; error: string | null; matchDecided: boolean }>({
    busy: false, error: null, matchDecided: false,
  })
  const { userId } = useAuth()
  // 保存に失敗したラリーは IndexedDB に退避してあり、ここで再送する
  useOfflineSync(matchId, userId)

  useEffect(() => {
    if (!matchId) return
    let cancelled = false
    setInitError(null)
    const run = async () => {
      try {
        const [stateRes, setsRes] = await Promise.all([
          apiGet<{ data: AnnotationStateLite }>(`/annotation/${matchId}/state`),
          apiGet<{ data: Array<{ id: number; set_num: number }> }>(`/sets/match/${matchId}`),
        ])
        const plan = planLiveStart(stateRes.data, setsRes.data)
        let set = plan.set
        if (!set) {
          // 試合にまだセットが無い。重複作成されない API なので作成する。
          const created = await apiPost<{ data: { id: number } }>('/sets', {
            match_id: matchId,
            set_num: plan.setNum,
          })
          set = { id: created.data.id, set_num: plan.setNum }
        }
        if (cancelled) return
        const cur = useAnnotationStore.getState()
        const reinit = shouldReinitFromServer(
          {
            matchId: cur.matchId,
            currentSetId: cur.currentSetId,
            pendingSaveCount: cur.pendingSaveCount,
            saveErrorCount: cur.saveErrors.length,
          },
          matchId,
          set.id,
        )
        if (reinit) {
          if (plan.server) {
            cur.init(matchId, set.id, set.set_num, plan.rallyNum, plan.scoreA, plan.scoreB, plan.server)
          } else {
            // 先サーブが不明。player_a を仮定せず、入力者に選んでもらう。
            setNeedServer({ setId: set.id, setNum: set.set_num, rallyNum: plan.rallyNum, scoreA: plan.scoreA, scoreB: plan.scoreB })
            return
          }
        }
        setNeedServer(null)
        setLiveSet(set)
      } catch (e: unknown) {
        if (!cancelled) {
          setInitError(errorMessage(e, t('annotator.live.init_failed')))
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  // t は言語切替で変わるが再取得は不要
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId, initNonce])

  const chooseStartServer = useCallback((server: Side) => {
    if (!matchId || !needServer) return
    useAnnotationStore.getState().init(
      matchId, needServer.setId, needServer.setNum, needServer.rallyNum,
      needServer.scoreA, needServer.scoreB, server,
    )
    setLiveSet({ id: needServer.setId, set_num: needServer.setNum })
    setNeedServer(null)
  }, [matchId, needServer])

  const latestSet = liveSet

  // 監査 #722: セットの勝敗が付いている間、このセットの端末退避 (再送待ち) 件数を読み続ける。
  // 保存中・保存エラー・再送待ちのいずれかが残る間はセット終了と次セット作成を止める。
  const [queuedForSet, setQueuedForSet] = useState(0)
  const setDecided = setWinner({ scoreA: store.scoreA, scoreB: store.scoreB }) !== null
  const latestSetId = latestSet?.id ?? null
  useEffect(() => {
    if (!matchId || latestSetId == null || !setDecided) return
    let cancelled = false
    const refresh = () => {
      loadQueuedRallyCount(userId, matchId, latestSetId)
        .then((n) => { if (!cancelled) setQueuedForSet(n) })
        .catch(() => { /* 読めないときは直前の値を保つ。確定時に再確認する */ })
    }
    refresh()
    const timer = setInterval(refresh, 2000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [matchId, latestSetId, setDecided, userId, store.pendingSaveCount, store.saveErrors.length])
  const saveBlocksSetEnd = isSetEndBlockedBySave({
    pendingSaveCount: store.pendingSaveCount,
    saveErrorCount: store.saveErrors.length,
    queuedForSet,
  })

  // ストローク入力直後の自動 RESULT 切替: hot-loop で即時得点判定したい場面に備えて、
  // OOB / NET 落点後 (=inputStep === 'rally_end') では RESULT モードに自動遷移
  useEffect(() => {
    if (store.inputStep === 'rally_end' && mode === 'rally') {
      setMode('result')
    }
  }, [store.inputStep, mode])

  if (!matchId) {
    return <div className="p-4 text-sm text-[var(--ss-t1)]">{t('auto.LiveInputPage.match_id_missing')}</div>
  }
  if (initError) {
    return (
      <div className="p-4 flex flex-col gap-3 text-sm text-[var(--ss-t1)]">
        <div>{t('annotator.live.init_failed')}</div>
        <div className="text-xs text-[var(--ss-t3)] break-all">{initError}</div>
        <button
          type="button"
          onClick={() => setInitNonce((n) => n + 1)}
          className="self-start px-3 py-2 rounded-[5px] bg-[var(--ss-brand)] text-white"
        >
          {t('annotator.live.init_retry')}
        </button>
      </div>
    )
  }
  // 監査 #721: 試合情報だけ取得に失敗したときに「読み込み中」で止めない。
  if (matchError && !match) {
    return (
      <div className="p-4 text-[var(--ss-t1)]">
        <QueryErrorNotice onRetry={() => { void refetchMatch() }} />
      </div>
    )
  }
  if (needServer && match) {
    return (
      <div className="p-4 flex flex-col gap-3 text-sm text-[var(--ss-t1)]">
        <div>{t('annotator.live.choose_server')}</div>
        <div className="flex gap-2">
          <button type="button" onClick={() => chooseStartServer('player_a')} className="flex-1 px-3 py-3 rounded-[5px] bg-[var(--ss-surface-2)]">
            {match.player_a?.name ?? 'A'}
          </button>
          <button type="button" onClick={() => chooseStartServer('player_b')} className="flex-1 px-3 py-3 rounded-[5px] bg-[var(--ss-surface-2)]">
            {match.player_b?.name ?? 'B'}
          </button>
        </div>
      </div>
    )
  }
  if (!match || !latestSet) {
    return <div className="p-4 text-sm text-[var(--ss-t3)]">{t('annotator.loading', { defaultValue: '読み込み中...' })}</div>
  }

  const handleShot = (shotType: ShotType) => {
    if (mode !== 'rally') return
    const ts = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000
    store.inputShotType(shotType, ts)
  }

  // セットの勝敗が成立した後は得点を積まない。次のセットへ進む操作だけを許す。
  const currentSetWinner = setWinner({ scoreA: store.scoreA, scoreB: store.scoreB })

  // セット終了: GameSet の勝者・最終スコアを確定し、試合が決着していなければ次のセットを作る。
  const handleEndSet = async () => {
    if (!latestSet || setEndState.busy) return
    const cur = useAnnotationStore.getState()
    const score = { scoreA: cur.scoreA, scoreB: cur.scoreB }
    const side = setWinner(score)
    if (side === null) return
    // 最終ラリーの保存が終わるまで確定しない。画面の値は最長 2 秒遅れるため、
    // 押下時に退避キューを読み直して確かめる。
    const queued = await loadQueuedRallyCount(userId, matchId, latestSet.id).catch(() => 0)
    if (
      isSetEndBlockedBySave({
        pendingSaveCount: cur.pendingSaveCount,
        saveErrorCount: useAnnotationStore.getState().saveErrors.length,
        queuedForSet: queued,
      })
    ) {
      setQueuedForSet(queued)
      return
    }
    setSetEndState({ busy: true, error: null, matchDecided: false })
    try {
      await apiPut(`/sets/${latestSet.id}/end`, {
        winner: side === 'A' ? 'player_a' : 'player_b',
        score_a: score.scoreA,
        score_b: score.scoreB,
      })
      const setsRes = await apiGet<{
        data: Array<{ id: number; set_num: number; winner?: 'player_a' | 'player_b' | null }>
      }>(`/sets/match/${matchId}`)
      const previous: Array<'A' | 'B'> = []
      for (const gs of setsRes.data) {
        if (gs.id === latestSet.id) continue
        if (gs.winner === 'player_a') previous.push('A')
        else if (gs.winner === 'player_b') previous.push('B')
      }
      if (isMatchDecidedBySet(previous, score)) {
        setSetEndState({ busy: false, error: null, matchDecided: true })
        return
      }
      const nextNum = latestSet.set_num + 1
      const created = await apiPost<{ data: { id: number } }>('/sets', {
        match_id: matchId,
        set_num: nextNum,
      })
      useAnnotationStore.getState().nextSet(created.data.id, nextNum)
      setLiveSet({ id: created.data.id, set_num: nextNum })
      setSetEndState({ busy: false, error: null, matchDecided: false })
    } catch (e: unknown) {
      setSetEndState({
        busy: false,
        error: errorMessage(e, t('annotator.ui.unknown_error')),
        matchDecided: false,
      })
    }
  }

  const handleConfirmResult = (winner: 'player_a' | 'player_b', endType: string) => {
    if (!latestSet) return
    if (currentSetWinner !== null) return
    const strokes = [...store.currentStrokes]
    const rallyNum = store.currentRallyNum
    const newScoreA = winner === 'player_a' ? store.scoreA + 1 : store.scoreA
    const newScoreB = winner === 'player_b' ? store.scoreB + 1 : store.scoreB
    // confirmRally は currentPlayer を勝者に書き換えるため、payload に使う値は
    // 確定の「前」に capture する (空ラリーの server が勝者で汚染されるのを防ぐ)。
    const server = store.currentPlayer
    const rallyStart = store.rallyStartTimestamp

    // #664: 取り消しに備えて確定「前」の値を控える。confirmRally はこの直後に
    // currentStrokes / score / server を書き換えるため、ここで capture しないと戻せない。
    const undoSnapshot: ConfirmedRallySnapshot = {
      scoreA: store.scoreA,
      scoreB: store.scoreB,
      rallyNum,
      server,
    }

    store.confirmRally(winner, endType)
    store.incrementPending()
    setLastConfirmed({
      snapshot: undoSnapshot,
      winner,
      endType,
      rallyId: null,
      saving: true,
      saveFailed: false,
      pendingResend: false,
      undoing: false,
      undoError: null,
    })
    const setId = latestSet.id

    const payload = strokes.length > 0
      ? buildBatchPayload({
          setId: latestSet.id,
          rallyNum,
          winner,
          endType,
          strokes,
          scoreAAfter: newScoreA,
          scoreBAfter: newScoreB,
          rallyStartTimestamp: rallyStart,
          isBasicMode: true,  // LiveInputPage は basic mode 固定 (試合中の素早い入力前提)
        })
      : buildSkippedRallyPayload({
          setId: latestSet.id,
          rallyNum,
          server,
          winner,
          scoreAAfter: newScoreA,
          scoreBAfter: newScoreB,
          isBasicMode: true,
        })

    // 送信前に端末へ退避し、成功を確認してから消す。失敗したら画面に出し、
    // 退避したラリーは useOfflineSync が再送する (成功扱いにしない)。
    const ownerId = userId
    const stableKey = ownerId != null
      ? offlineStrokeIdempotencyKey(ownerId, matchId, setId, rallyNum)
      : undefined
    const stashed = stashRallyBeforeSave(ownerId, {
      matchId,
      setId,
      rallyNum,
      payload,
      queued_at: new Date().toISOString(),
    })
    apiPost<{ data?: { rally_id?: number } }>('/strokes/batch', payload, stableKey ? { 'X-Idempotency-Key': stableKey } : undefined)
      .then((res) => {
        useAnnotationStore.getState().decrementPending()
        void stashed.then(() => removeRallyAfterSave(ownerId, matchId, setId, rallyNum))
        // #664: 保存できた rally_id を取り消し用に控える。これが取れて初めて
        // server 側の削除ができる。取り消しボタンは saving=false になって押せる。
        const savedRallyId = res?.data?.rally_id ?? null
        setLastConfirmed((prev) =>
          prev && prev.snapshot.rallyNum === rallyNum
            ? { ...prev, rallyId: savedRallyId, saving: false, saveFailed: false, pendingResend: false }
            : prev,
        )
      })
      .catch((err: unknown) => {
        useAnnotationStore.getState().decrementPending()
        // 要望2: 「保存し終わったはずが保存失敗と出る」の是正。
        // 失敗を一過性 (タイムアウト・通信断・5xx・429・408) と恒久的 (4xx) に分ける。
        // - 一過性: サーバはこのラリーを既に保存している可能性があり、退避は端末に残って
        //   useOfflineSync が同じ冪等キーで再送するため二重にならず最終的に整合する。
        //   「保存失敗」と赤く断定せず、「再送待ち (自動で再送)」として扱う (saveErrors に積まない)。
        // - 恒久的: 冪等キーで送り直しても同じ 4xx になる本当の失敗。saveErrors に積んで確認させる。
        const decision = classifyConfirmSaveFailure(err)
        if (decision.pushSaveError) {
          useAnnotationStore.getState().addSaveError({
            rallyNum,
            error: errorMessage(err, t('annotator.ui.save_failed_message', { defaultValue: '保存失敗' })),
          })
        }
        // #664: server 側 rally はまだ存在しないので、取り消しはローカルのみ可能とする。
        setLastConfirmed((prev) =>
          prev && prev.snapshot.rallyNum === rallyNum
            ? {
                ...prev,
                rallyId: null,
                saving: false,
                saveFailed: decision.saveFailed,
                pendingResend: decision.pendingResend,
              }
            : prev,
        )
      })
    setMode('rally')
  }

  // #664: 直前に確定した得点を取り消す。
  //  - 保存済み (rallyId あり): server の DELETE /rallies/{id} を先に成功させ、
  //    そのうえでローカル状態を確定前へ戻す。削除が失敗したら store は戻さない
  //    (画面と DB が食い違わないようにする)。
  //  - 未保存で保存失敗 (saveFailed, rallyId なし): server にラリーは無い。再送
  //    キューから除いてローカルだけ戻す。
  //  - 保存中 (saving): まだ rallyId が確定しないので取り消しを受け付けない
  //    (UI 側で無効化。二重押し等でここに来たら何もしない)。
  const handleUndoLastConfirmed = async () => {
    const lc = lastConfirmed
    if (!lc || lc.saving || lc.undoing) return

    if (lc.rallyId != null) {
      setLastConfirmed({ ...lc, undoing: true, undoError: null })
      try {
        await apiDelete(`/rallies/${lc.rallyId}`, { 'X-Idempotency-Key': newIdempotencyKey() })
      } catch (err: unknown) {
        setLastConfirmed({
          ...lc,
          undoing: false,
          undoError: errorMessage(err, t('annotator.ui.unknown_error')),
        })
        return
      }
      store.undoLastConfirmedRally(lc.snapshot)
      setLastConfirmed(null)
      setMode('rally')
      return
    }

    // 保存に至っていないラリー (恒久的な保存失敗、または一過性で再送待ち): 取り消しは
    // 退避キューから除いてローカルを戻す。rallyId が無いため server の DELETE は呼べない
    // (保存できていれば次の再送で入るが、取り消しの意思表示として再送キューからは外す)。
    if (lc.saveFailed || lc.pendingResend) {
      void removeRallyAfterSave(userId, matchId, latestSet.id, lc.snapshot.rallyNum)
      store.undoLastConfirmedRally(lc.snapshot)
      // 保存失敗で積んだ saveError も取り消す (このラリーの分)。
      store.clearSaveErrors()
      setLastConfirmed(null)
      setMode('rally')
    }
  }

  const playerAName = match.player_a?.name ?? 'A'
  const playerBName = match.player_b?.name ?? 'B'

  return (
    <div className="fixed inset-0 bg-[var(--ss-bg-app)] text-[var(--ss-t1)] flex flex-col">
      {/* トップバー: 戻る + スコア */}
      <header className="flex items-center justify-between px-3 py-2 border-b border-[var(--ss-border)] shrink-0">
        <button
          type="button"
          onClick={() => navigate('/matches')}
          className="text-sm text-[var(--ss-t2)] px-2 py-1 hover:bg-[var(--ss-surface-2)] rounded-[5px]"
          aria-label={t('annotator.back_to_matches', { defaultValue: '試合一覧に戻る' })}
        >
          ←
        </button>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-[var(--ss-t2)] truncate max-w-[8rem]">{playerAName}</span>
          <span className="text-3xl font-mono font-bold ss-num">{store.scoreA}</span>
          <span className="text-[var(--ss-t3)]">-</span>
          <span className="text-3xl font-mono font-bold ss-num">{store.scoreB}</span>
          <span className="text-[var(--ss-t2)] truncate max-w-[8rem]">{playerBName}</span>
        </div>
        <div className="text-[10px] text-[var(--ss-t3)] flex flex-col items-end gap-0.5">
          <span>
            {t('annotator.set', { defaultValue: 'ゲーム' })} <span className="ss-num">{store.currentSetNum}</span>
          </span>
          {store.pendingSaveCount > 0 && (
            <span>{t('annotator.live.saving_count', { n: store.pendingSaveCount })}</span>
          )}
          {store.saveErrors.length > 0 && (
            <button
              type="button"
              onClick={() => store.clearSaveErrors()}
              className="text-[var(--ss-bad)] font-bold"
              title={store.saveErrors.map((e) => `Rally ${e.rallyNum}: ${e.error}`).join('\n')}
            >
              {t('annotator.live.unsaved_count', { n: store.saveErrors.length })}
            </button>
          )}
        </div>
      </header>

      {/* モードタブ */}
      <div className="flex border-b border-[var(--ss-border)] shrink-0" role="tablist">
        <button
          role="tab"
          aria-selected={mode === 'rally'}
          onClick={() => setMode('rally')}
          className={
            'flex-1 py-2 text-sm font-medium ' +
            (mode === 'rally' ? 'bg-[var(--ss-brand)] text-white' : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)]')
          }
        >
          {t('annotator.live.tab_rally', { defaultValue: 'ラリー入力' })}
        </button>
        <button
          role="tab"
          aria-selected={mode === 'result'}
          onClick={() => setMode('result')}
          className={
            'flex-1 py-2 text-sm font-medium ' +
            (mode === 'result' ? 'bg-[var(--ss-emphasis)] text-white' : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)]')
          }
        >
          {t('annotator.live.tab_result', { defaultValue: '得点確定' })}
        </button>
      </div>

      {/* #664: 直前に確定した得点の取り消し導線。確定直後の誤タップをその場で戻せる。
          得点者・終了種別・保存状態を併記し、保存完了後に取り消しが押せる。 */}
      {lastConfirmed !== null && (
        <div role="status" className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-[var(--ss-border)] text-sm">
          <span className="flex-1 text-[var(--ss-t2)] truncate">
            {t('annotator.live.last_result', {
              player: lastConfirmed.winner === 'player_a' ? playerAName : playerBName,
              endType: t(`end_types.${lastConfirmed.endType}`, { defaultValue: lastConfirmed.endType }),
            })}
            {lastConfirmed.saving && (
              <span className="ml-2 text-xs text-[var(--ss-t3)]">{t('annotator.live.saving_count', { n: 1 })}</span>
            )}
            {lastConfirmed.pendingResend && (
              <span className="ml-2 text-xs text-[var(--ss-t2)]">{t('annotator.live.result_pending_resend')}</span>
            )}
          </span>
          <button
            type="button"
            disabled={lastConfirmed.saving || lastConfirmed.undoing}
            onClick={() => { void handleUndoLastConfirmed() }}
            className="px-3 py-2 rounded-[5px] bg-[var(--ss-surface-2)] text-[var(--ss-t1)] border border-[var(--ss-border-strong)] disabled:opacity-50"
          >
            {lastConfirmed.undoing
              ? t('annotator.live.undo_confirmed_busy')
              : t('annotator.live.undo_confirmed')}
          </button>
        </div>
      )}
      {lastConfirmed?.saving && (
        <div role="status" className="shrink-0 px-3 py-1 text-xs text-[var(--ss-t2)]">
          {t('annotator.live.undo_wait_save')}
        </div>
      )}
      {lastConfirmed?.undoError && (
        <div className="shrink-0 px-3 py-1 text-xs text-[var(--ss-bad)] break-all">
          {t('annotator.live.undo_failed', { reason: lastConfirmed.undoError })}
        </div>
      )}

      {/* セット決着: 次のセットへ (試合が決着していれば終了表示) */}
      {currentSetWinner !== null && (
        <div role="status" className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-[var(--ss-border)] text-sm">
          <span className="flex-1">
            {setEndState.matchDecided
              ? t('annotator.live.match_decided')
              : t('annotator.live.set_decided', { a: store.scoreA, b: store.scoreB })}
          </span>
          {!setEndState.matchDecided && (
            <button
              type="button"
              disabled={setEndState.busy || saveBlocksSetEnd}
              onClick={() => { void handleEndSet() }}
              className="px-3 py-2 rounded-[5px] bg-[var(--ss-brand)] text-white disabled:opacity-50"
            >
              {setEndState.busy ? t('annotator.live.set_end_busy') : t('annotator.live.next_set')}
            </button>
          )}
        </div>
      )}
      {currentSetWinner !== null && !setEndState.matchDecided && saveBlocksSetEnd && (
        <div role="status" className="shrink-0 px-3 py-1 text-xs text-[var(--ss-t2)]">
          {t('annotator.live.set_end_waiting_save')}
        </div>
      )}
      {setEndState.error && (
        <div className="shrink-0 px-3 py-1 text-xs text-[var(--ss-bad)] break-all">
          {t('annotator.live.set_end_failed', { reason: setEndState.error })}
        </div>
      )}

      {/* メインエリア (mode 別) */}
      <div className="flex-1 overflow-y-auto p-3">
        {mode === 'rally' ? (
          <div className="flex flex-col gap-3">
            <AttributePanel
              attributes={store.pendingStroke}
              onChange={(attrs) => {
                if (attrs.is_backhand !== store.pendingStroke.is_backhand) store.toggleAttribute('is_backhand')
                if (attrs.is_around_head !== store.pendingStroke.is_around_head) store.toggleAttribute('is_around_head')
                if (attrs.above_net !== store.pendingStroke.above_net) store.setAboveNet(attrs.above_net)
                if (attrs.hit_height !== store.pendingStroke.hit_height) store.setHitHeight(attrs.hit_height)
              }}
            />
            <ShotTypePanel
              selected={store.pendingStroke.shot_type ?? null}
              onSelect={handleShot}
              strokeNum={store.currentStrokeNum}
              lastShotType={store.currentStrokes[store.currentStrokes.length - 1]?.shot_type ?? null}
              isMatchDayMode  // LiveInputPage は常に試合中モード = 大きめタイル
            />
          </div>
        ) : (
          <RallyPanel
            setNum={store.currentSetNum}
            rallyNum={store.currentRallyNum}
            scoreA={store.scoreA}
            scoreB={store.scoreB}
            playerAName={playerAName}
            playerBName={playerBName}
            onConfirmRally={handleConfirmResult}
            onCancelRally={() => {
              store.resetRally()
              setMode('rally')
            }}
            isActive={true}
          />
        )}
      </div>
    </div>
  )
}
