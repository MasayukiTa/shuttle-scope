/**
 * オフライン耐性: 起動時 + ネットワーク復帰時に未送信ラリーを再送する。
 *
 * Phase A 実装。AnnotatorPage マウント時に呼ぶ。
 *
 * 仕様:
 *   - 起動時に 1 回 sync
 *   - online イベントで sync
 *   - 30 秒ごとにも try (online イベントが発火しないケースの保険)
 *   - 失敗したら次回まで stash に残す（exponential backoff なし、シンプル）
 */
import { useEffect, useRef } from 'react'

import { apiPost } from '@/api/client'
import {
  countPendingForUserStrict,
  isResendHeld,
  listDraftsForMatch,
  listPendingForMatch,
  offlineStrokeIdempotencyKey,
  removeDraftRally,
  removePending,
} from '@/utils/offlineStrokeQueue'
import { buildBatchPayloadFromDraftSnapshot } from '@/utils/annotationPayload'
import { deriveSyncStatus } from '@/utils/syncStatus'
import { useAnnotationStore } from '@/store/annotationStore'
// hook の外では useTranslation の t が束縛されない。CLAUDE.md の規約どおり
// 修飾済みの i18n.t を使う。
import i18n from '@/i18n'

const POLL_INTERVAL_MS = 30_000

interface BatchResult {
  success: boolean
  data?: { rally_id: number; stroke_count: number }
}

export function useOfflineSync(matchId: number | null, ownerUserId: number | null): void {
  const inflightRef = useRef(false)
  // sync 実行中に来た再実行要求 (online / ポーリング / 起動) を取りこぼさない。
  // 実行中なら「終わったらもう一度」を立て、完了後にもう一度だけ流す。これが無いと
  // 起動時 sync が IndexedDB 待ちで in-flight の間に online イベントが来た場合、その
  // 1 回が握り潰され、次の送信は 30 秒後のポーリングまで来ない (Windows CI で顕著)。
  const rerunRef = useRef(false)

  useEffect(() => {
    if (matchId == null || ownerUserId == null) return

    // 表示更新: 本人の未送信件数を IndexedDB から数え直し、navigator.onLine と
    // 直近の送信が失敗したかから表示状態を導き、store へ反映する。
    const refreshStatus = async (lastSendFailed: boolean) => {
      let unsentCount = 0
      try {
        unsentCount = await countPendingForUserStrict(ownerUserId)
      } catch {
        // 読み取りに失敗したら前の件数を維持する (0 と偽らない)。
        unsentCount = useAnnotationStore.getState().unsentCount
      }
      const offline = typeof navigator !== 'undefined' && navigator.onLine === false
      const view = deriveSyncStatus({ unsentCount, offline, lastSendFailed })
      useAnnotationStore.getState().setSyncStatus(view.unsentCount, view.state)
    }

    const sync = async () => {
      // 既に実行中なら、取りこぼさないよう再実行を予約して戻る。完了後に一度流す。
      if (inflightRef.current) {
        rerunRef.current = true
        return
      }
      // オフラインでも未送信件数・状態は常時更新する (表示を出し続ける)。
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        await refreshStatus(false)
        return
      }
      inflightRef.current = true
      let sendFailed = false
      try {
        const items = await listPendingForMatch(matchId, ownerUserId)
        for (const it of items) {
          // \u5fa9\u5143\u30c0\u30a4\u30a2\u30ed\u30b0\u304c\u51fa\u3066\u3044\u308b\u30e9\u30ea\u30fc\u306f\u3001\u5fa9\u5143\u304b\u7834\u68c4\u304c\u6c7a\u307e\u308b\u307e\u3067
          // \u9001\u3089\u306a\u3044\u3002\u3053\u3053\u3067\u9001\u308b\u3068\u3001\u307e\u3060\u5fa9\u5143\u5f85\u3061\u306e\u30e9\u30ea\u30fc\u306e owned \u884c\u304c
          // online \u5fa9\u5e30\u76f4\u5f8c\u306b\u518d\u9001\u3055\u308c\u3001\u5931\u6557\u6271\u3044\u3055\u308c\u3066\u300c\u4fdd\u5b58\u5931\u6557\u300d\u304c\u51fa\u308b
          // (muse \u5b9f\u6a5f 13:08)\u3002sendFailed \u306f\u7acb\u3066\u305a\u3001\u5f8c\u7d9a\u306f\u901a\u5e38\u901a\u308a\u51e6\u7406\u3059\u308b\u3002
          if (isResendHeld(it.matchId, it.setId, it.rallyNum)) continue
          // 本文 (payload) の無い行は送らない。draft 行などが所有権フィルタを
          // すり抜けても、ここで本文空の POST /strokes/batch (422) を出さずに残す。
          // (listPendingForMatch は既に payload 欠落を除外するが、二重の防御。)
          if (it.payload == null) continue
          try {
            // apiPost は既定で**毎回新しい** idempotency key を作る。再送のたびに
            // キーが変わると、サーバが「処理済みだが応答を失った」最初の送信と
            // 同じものだと判定できず、ラリーが二重に入る。キューの同一性
            // (match/set/rally) から安定キーを作って上書きする。
            const stableKey = offlineStrokeIdempotencyKey(
              ownerUserId,
              it.matchId,
              it.setId,
              it.rallyNum,
            )
            const res = await apiPost<BatchResult>('/strokes/batch', it.payload, {
              'X-Idempotency-Key': stableKey,
            })
            if (res?.success) {
              await removePending(ownerUserId, it.matchId, it.setId, it.rallyNum)
            }
          } catch (e) {
            // 旧実装は無条件 break だった。恒久的な 4xx (壊れたペイロード等) が
            // 1 件入ると、**その後ろのラリーが永久に送られない**まま無言で
            // 滞留する。再試行で直るもの (ネットワーク / 5xx / 429) だけ
            // 中断し、直らないものは捨てて先へ進む。
            const status = (e as { status?: number } | null)?.status
            const permanent =
              typeof status === 'number' &&
              status >= 400 && status < 500 &&
              status !== 408 && status !== 429
            if (permanent) {
              // 何度送っても通らない 1 件。**キューからは外さない** —
              // 注釈データを黙って捨てるのは、この機構が防ごうとしている
              // ことそのもの。後続を止めないために飛ばすだけにする。
              // (この件を操作者に見せる UI が無いのは別途の課題。
              //  今は「後続が全部止まる」ほうを先に止める)
              console.warn(
                `[offline-sync] rally ${it.setId}/${it.rallyNum} は ${status} で` +
                  ' 恒久的に拒否されています。後続を処理するため飛ばします。',
              )
              // **操作者に見せる。** 黙って飛ばすと、保存できたつもりのまま
              // 入力が続く。既存の保存エラー表示に同じ経路で載せる。
              // 同じラリーを毎回 30 秒ごとに積まないよう重複は入れない。
              const store = useAnnotationStore.getState()
              const already = store.saveErrors.some((e) => e.rallyNum === it.rallyNum)
              if (!already) {
                store.addSaveError({
                  rallyNum: it.rallyNum,
                  error: i18n.t('annotator.offline_sync_rejected', { status }),
                })
              }
              continue
            }
            // 再試行で直る種類 (ネットワーク / 5xx / 429 / 408)。未送信が残るので
            // 表示を failed にする。次回の online / ポーリングで再送される。
            sendFailed = true
            break
          }
        }
        // draft/ 行: snapshot から本文を組み立てて送る。payload を持たない draft 行は
        // 確定済み (winner / endType / スコアが揃う) のときだけ buildBatchPayloadFromDraftSnapshot が
        // 本文を返す。未確定 (入力途中) なら null が返り、送らず snapshot のまま残す
        // (未確定ラリーを虚偽の winner で送らない)。
        const drafts = await listDraftsForMatch(matchId, ownerUserId)
        for (const d of drafts) {
          if (isResendHeld(d.matchId, d.setId, d.rallyNum)) continue
          const payload = buildBatchPayloadFromDraftSnapshot(d.snapshot)
          if (payload == null) continue
          try {
            const stableKey = offlineStrokeIdempotencyKey(
              ownerUserId,
              d.matchId,
              d.setId,
              d.rallyNum,
            )
            const res = await apiPost<BatchResult>('/strokes/batch', payload, {
              'X-Idempotency-Key': stableKey,
            })
            if (res?.success) {
              await removeDraftRally(ownerUserId, d.matchId, d.setId, d.rallyNum)
            }
          } catch (e) {
            // 再試行で直る種類 (ネットワーク / 5xx / 429 / 408) だけ中断する。
            // 恒久的な 4xx は snapshot を捨てず残して次へ進む (注釈データを黙って消さない)。
            const status = (e as { status?: number } | null)?.status
            const permanent =
              typeof status === 'number' &&
              status >= 400 && status < 500 &&
              status !== 408 && status !== 429
            if (permanent) {
              console.warn(
                `[offline-sync] draft rally ${d.setId}/${d.rallyNum} は ${status} で` +
                  ' 恒久的に拒否されました。後続を処理するため飛ばします。',
              )
              continue
            }
            sendFailed = true
            break
          }
        }
      } finally {
        inflightRef.current = false
        await refreshStatus(sendFailed)
      }
      // 実行中に来ていた再実行要求を 1 回だけ消化する (online を握り潰さない)。
      if (rerunRef.current) {
        rerunRef.current = false
        await sync()
      }
    }

    void sync()

    const onOnline = () => { void sync() }
    if (typeof window !== 'undefined') {
      window.addEventListener('online', onOnline)
    }
    const interval = setInterval(() => { void sync() }, POLL_INTERVAL_MS)

    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('online', onOnline)
      }
      clearInterval(interval)
    }
  }, [matchId, ownerUserId])
}
