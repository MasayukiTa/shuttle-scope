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
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'

import { apiGet } from '@/api/client'
import { ShotTypePanel } from '@/components/annotation/ShotTypePanel'
import { AttributePanel } from '@/components/annotation/AttributePanel'
import { RallyPanel } from '@/components/annotation/RallyPanel'
import { useAnnotationStore } from '@/store/annotationStore'
import { buildBatchPayload, buildSkippedRallyPayload } from '@/utils/annotationPayload'
import { apiPost } from '@/api/client'
import type { Match, ShotType } from '@/types'

type LiveMode = 'rally' | 'result'

export function LiveInputPage() {
  const { matchId: matchIdStr } = useParams<{ matchId: string }>()
  const matchId = matchIdStr ? parseInt(matchIdStr, 10) : null
  const navigate = useNavigate()
  const { t } = useTranslation()

  const [mode, setMode] = useState<LiveMode>('rally')

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
  const { data: matchData } = useQuery<{ data: Match }>({
    queryKey: ['live-match', matchId],
    queryFn: () => apiGet(`/matches/${matchId}`),
    enabled: !!matchId,
    staleTime: 60_000,
  })

  const { data: setsData } = useQuery<{ data: Array<{ id: number; set_num: number }> }>({
    queryKey: ['live-sets', matchId],
    queryFn: () => apiGet(`/sets?match_id=${matchId}`),
    enabled: !!matchId,
    staleTime: 60_000,
  })

  const match = matchData?.data
  const latestSet = setsData?.data?.[setsData.data.length - 1]

  // 初期化 (1 回だけ)
  useEffect(() => {
    if (!matchId || !latestSet) return
    if (store.matchId === matchId && store.currentSetId === latestSet.id) return
    store.init(matchId, latestSet.id, latestSet.set_num, 1, 0, 0, 'player_a')
  }, [matchId, latestSet, store])

  // ストローク入力直後の自動 RESULT 切替: hot-loop で即時得点判定したい場面に備えて、
  // OOB / NET 落点後 (=inputStep === 'rally_end') では RESULT モードに自動遷移
  useEffect(() => {
    if (store.inputStep === 'rally_end' && mode === 'rally') {
      setMode('result')
    }
  }, [store.inputStep, mode])

  if (!matchId) {
    return <div className="p-4 text-sm">match id missing</div>
  }
  if (!match || !latestSet) {
    return <div className="p-4 text-sm text-gray-500">{t('annotator.loading', { defaultValue: '読み込み中...' })}</div>
  }

  const handleShot = (shotType: ShotType) => {
    if (mode !== 'rally') return
    const ts = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000
    store.inputShotType(shotType, ts)
  }

  const handleConfirmResult = (winner: 'player_a' | 'player_b', endType: string) => {
    if (!latestSet) return
    const strokes = [...store.currentStrokes]
    const rallyNum = store.currentRallyNum
    const newScoreA = winner === 'player_a' ? store.scoreA + 1 : store.scoreA
    const newScoreB = winner === 'player_b' ? store.scoreB + 1 : store.scoreB

    store.confirmRally(winner, endType)
    store.incrementPending()

    const payload = strokes.length > 0
      ? buildBatchPayload({
          setId: latestSet.id,
          rallyNum,
          winner,
          endType,
          strokes,
          scoreAAfter: newScoreA,
          scoreBAfter: newScoreB,
          rallyStartTimestamp: store.rallyStartTimestamp,
          isBasicMode: true,  // LiveInputPage は basic mode 固定 (試合中の素早い入力前提)
        })
      : buildSkippedRallyPayload({
          setId: latestSet.id,
          rallyNum,
          server: store.currentPlayer,
          winner,
          scoreAAfter: newScoreA,
          scoreBAfter: newScoreB,
          isBasicMode: true,
        })

    apiPost('/strokes/batch', payload).finally(() => {
      useAnnotationStore.getState().decrementPending()
    })
    setMode('rally')
  }

  const playerAName = match.player_a?.name ?? 'A'
  const playerBName = match.player_b?.name ?? 'B'

  return (
    <div className="fixed inset-0 bg-gray-950 text-gray-100 flex flex-col">
      {/* トップバー: 戻る + スコア */}
      <header className="flex items-center justify-between px-3 py-2 border-b border-gray-800 shrink-0">
        <button
          type="button"
          onClick={() => navigate('/matches')}
          className="text-sm text-gray-300 px-2 py-1 hover:bg-gray-800 rounded"
          aria-label={t('annotator.back_to_matches', { defaultValue: '試合一覧に戻る' })}
        >
          ←
        </button>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-400 truncate max-w-[8rem]">{playerAName}</span>
          <span className="text-3xl font-mono font-bold tabular-nums">{store.scoreA}</span>
          <span className="text-gray-500">-</span>
          <span className="text-3xl font-mono font-bold tabular-nums">{store.scoreB}</span>
          <span className="text-gray-400 truncate max-w-[8rem]">{playerBName}</span>
        </div>
        <div className="text-[10px] text-gray-500">
          {t('annotator.set', { defaultValue: 'セット' })} {store.currentSetNum}
        </div>
      </header>

      {/* モードタブ */}
      <div className="flex border-b border-gray-800 shrink-0" role="tablist">
        <button
          role="tab"
          aria-selected={mode === 'rally'}
          onClick={() => setMode('rally')}
          className={
            'flex-1 py-2 text-sm font-medium ' +
            (mode === 'rally' ? 'bg-blue-700 text-white' : 'bg-gray-900 text-gray-400')
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
            (mode === 'result' ? 'bg-orange-600 text-white' : 'bg-gray-900 text-gray-400')
          }
        >
          {t('annotator.live.tab_result', { defaultValue: '得点確定' })}
        </button>
      </div>

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
