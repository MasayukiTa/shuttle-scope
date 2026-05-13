/**
 * MobileAnnotatePage (R48 step 1)
 *
 * iPhone Safari 専用のスマホアノテーション画面。AnnotatorPage (PC/iPad 用) と
 * 別実装にして、選手が試合中・試合後にスマホ片手で入力できる UI に特化する。
 *
 * 設計思想 (詳細は別ドキュメント):
 *   - Play mode / Annotate mode を厳密に分離して干渉ゼロ
 *   - 3 つの Pass を自由順で切替可:
 *       Pass 1: ラリー区切り (得点入った瞬間 = rally end timestamp)
 *       Pass 2: サーブ打点 / サーブ着地 / 最終打点 / 最終着地
 *       Pass 3: 各ストロークの詳細 (shot type, hit zone)
 *   - クロップ領域: 鳥瞰固定カメラの不要部分を切り抜いて再生
 *   - 各入力ごとに即サーバ送信 + ローカル冗長キャッシュ (IndexedDB)
 *   - 認知負荷を最大限下げる: 1 画面で 1 判断
 *
 * 現状 (commit 1): scaffold + landscape guard + Pass 切替 UI 雛形のみ。
 * 次 commit で動画再生 + crop region。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Play, Crosshair, Layers, CloudOff, AlertTriangle } from 'lucide-react'
import { apiGet, apiPost } from '@/api/client'
import { getVideoSrc } from '@/utils/videoSrc'
import { PlayMode } from '@/components/mobileAnnotate/PlayMode'
import { Pass1RallyEnd } from '@/components/mobileAnnotate/Pass1RallyEnd'
import { startBackgroundFlush, getStatus, retryAllManual } from '@/utils/mobileAnnotateQueue'

type ScreenMode = 'play' | 'annotate'

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

export type AnnotatePass = 'rally' | 'serve_final' | 'detail'

const PASS_LABELS: Record<AnnotatePass, string> = {
  rally: 'Pass 1: 得点',
  serve_final: 'Pass 2: サーブ・決定打',
  detail: 'Pass 3: 詳細',
}

const PASS_ICONS: Record<AnnotatePass, React.ReactNode> = {
  rally: <Play size={14} />,
  serve_final: <Crosshair size={14} />,
  detail: <Layers size={14} />,
}


/**
 * 横向きを促す guard。iOS Safari は CSS の orientation lock を尊重しないため、
 * 画面サイズで縦向きを検知して overlay を出す。
 */
function LandscapeGuard({ children }: { children: React.ReactNode }) {
  const [isPortrait, setIsPortrait] = useState<boolean>(() =>
    typeof window !== 'undefined' && window.innerHeight > window.innerWidth,
  )

  useEffect(() => {
    const onResize = () => setIsPortrait(window.innerHeight > window.innerWidth)
    window.addEventListener('resize', onResize)
    window.addEventListener('orientationchange', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('orientationchange', onResize)
    }
  }, [])

  if (isPortrait) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black text-white p-6 text-center">
        <div className="text-5xl mb-4">📱↻</div>
        <h2 className="text-lg font-semibold mb-2">端末を横向きに</h2>
        <p className="text-sm text-gray-300">
          スマホアノテーションは横向き専用です。<br />
          端末を回転させてください。
        </p>
      </div>
    )
  }
  return <>{children}</>
}


export function MobileAnnotatePage() {
  const { t } = useTranslation()
  const { matchId } = useParams<{ matchId: string }>()
  const navigate = useNavigate()
  const [pass, setPass] = useState<AnnotatePass>('rally')
  const [screen, setScreen] = useState<ScreenMode>('play')
  const [pausedAtSec, setPausedAtSec] = useState<number>(0)
  const videoElRef = useRef<HTMLVideoElement | null>(null)
  const [queueStatus, setQueueStatus] = useState<{
    pending: number
    manualRetry: number
  }>({ pending: 0, manualRetry: 0 })

  // match 情報を取得 (動画 URL を得るため)
  const matchQuery = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => apiGet<{ data: any }>(`/matches/${matchId}`),
    enabled: !!matchId,
  })
  const match = matchQuery.data?.data
  const videoSrc = getVideoSrc(match)

  // セット一覧 + 既存ラリー取得 (Pass 1 用)
  const setsQuery = useQuery({
    queryKey: ['mobile-annot-sets', matchId],
    queryFn: () => apiGet<{ data: any[] }>(`/sets?match_id=${matchId}`),
    enabled: !!matchId,
  })
  const ralliesQuery = useQuery({
    queryKey: ['mobile-annot-rallies', matchId],
    queryFn: () => apiGet<{ data: any[] }>(`/rallies?match_id=${matchId}`),
    enabled: !!matchId,
  })

  const [localRallies, setLocalRallies] = useState<RallyLite[]>([])
  const [currentSetIdx, setCurrentSetIdx] = useState<number>(0)

  const allSets: SetInfo[] = useMemo(() => {
    const rows = setsQuery.data?.data ?? []
    return rows.map((s: any) => ({ id: s.id, set_num: s.set_num }))
      .sort((a: SetInfo, b: SetInfo) => a.set_num - b.set_num)
  }, [setsQuery.data])

  const serverRallies: RallyLite[] = useMemo(() => {
    const rows = ralliesQuery.data?.data ?? []
    return rows.map((r: any) => ({
      id: r.id,
      client_uuid: r.uuid ?? '',
      set_id: r.set_id,
      rally_num: r.rally_num,
      server: r.server,
      winner: r.winner,
      score_a_after: r.score_a_after ?? 0,
      score_b_after: r.score_b_after ?? 0,
      video_timestamp_end: r.video_timestamp_end ?? 0,
      pending: false,
    }))
  }, [ralliesQuery.data])

  const mergedRallies = useMemo(() => {
    // server + local の合算、rally_num で順序
    const all = [...serverRallies, ...localRallies]
    return all.sort((a, b) => {
      if (a.set_id !== b.set_id) return a.set_id - b.set_id
      return a.rally_num - b.rally_num
    })
  }, [serverRallies, localRallies])

  const currentSet = allSets[currentSetIdx]

  const ensureSet = async (): Promise<SetInfo | null> => {
    if (currentSet) return currentSet
    if (!matchId) return null
    try {
      const resp: any = await apiPost(`/sets`, {
        match_id: Number(matchId), set_num: 1,
      })
      const newSet: SetInfo = { id: resp.data?.id ?? resp.id, set_num: 1 }
      setsQuery.refetch()
      return newSet
    } catch {
      return null
    }
  }

  // body スクロール抑止: 全画面で固定
  useEffect(() => {
    const orig = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = orig
    }
  }, [])

  // 送信キューを起動 + ステータスを 2 秒ごとにポーリング (UI 表示用)
  useEffect(() => {
    startBackgroundFlush()
    let cancelled = false
    const tick = async () => {
      const s = await getStatus()
      if (!cancelled) setQueueStatus({ pending: s.pending, manualRetry: s.manualRetry })
    }
    void tick()
    const id = window.setInterval(tick, 2000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  return (
    <LandscapeGuard>
      <div className="fixed inset-0 bg-black text-white flex flex-col touch-none select-none">
        {/* ヘッダ: 戻る + 試合 + Pass 切替 */}
        <div className="flex items-center gap-2 bg-black/80 backdrop-blur px-2 py-1.5 border-b border-gray-800 text-xs">
          <button
            type="button"
            onClick={() => navigate('/matches')}
            className="p-1.5 rounded hover:bg-gray-800"
            aria-label="戻る"
          >
            <ArrowLeft size={16} />
          </button>
          <span className="font-mono text-[11px] text-gray-400">
            match #{matchId ?? '?'}
          </span>
          {/* 未送信キュー状況 */}
          {queueStatus.pending > 0 && (
            <span
              className="flex items-center gap-1 text-[10px] text-amber-300"
              title={`未送信 ${queueStatus.pending} 件 (バックグラウンド再送中)`}
            >
              <CloudOff size={12} />
              {queueStatus.pending}
            </span>
          )}
          {queueStatus.manualRetry > 0 && (
            <button
              type="button"
              onClick={() => void retryAllManual()}
              className="flex items-center gap-1 text-[10px] text-red-300 hover:text-red-200 px-1 py-0.5 rounded border border-red-500"
              title={`送信失敗 ${queueStatus.manualRetry} 件 — タップで再送`}
            >
              <AlertTriangle size={12} />
              {queueStatus.manualRetry}
            </button>
          )}
          <div className="flex-1" />
          {/* Pass 切替チップ */}
          <div className="flex gap-1">
            {(Object.keys(PASS_LABELS) as AnnotatePass[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPass(p)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                  pass === p
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                {PASS_ICONS[p]}
                <span>{PASS_LABELS[p]}</span>
              </button>
            ))}
          </div>
        </div>

        {/* 本体 */}
        <div className="flex-1 flex flex-col min-h-0 bg-gray-950 relative">
          {matchQuery.isLoading ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
              読み込み中...
            </div>
          ) : matchQuery.error ? (
            <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
              試合情報の取得に失敗しました
            </div>
          ) : screen === 'play' ? (
            <PlayMode
              matchId={matchId ?? ''}
              videoSrc={videoSrc}
              onTapVideo={(t) => {
                setPausedAtSec(t)
                setScreen('annotate')
              }}
              videoElRef={(el) => { videoElRef.current = el }}
            />
          ) : pass === 'rally' ? (
            // Pass 1: 得点ラリー区切り
            (() => {
              if (!currentSet) {
                // セットが未作成: 1 タップで作る誘導
                return (
                  <div className="flex-1 flex flex-col items-center justify-center text-gray-300 text-sm gap-3">
                    <div className="text-sm">
                      この試合にはまだセットが登録されていません
                    </div>
                    <button
                      type="button"
                      onClick={async () => {
                        const s = await ensureSet()
                        if (s) setCurrentSetIdx(0)
                      }}
                      className="px-4 py-2 rounded bg-blue-600 text-white text-sm"
                    >
                      セット 1 を作成して開始
                    </button>
                    <button
                      type="button"
                      onClick={() => setScreen('play')}
                      className="px-3 py-1.5 bg-gray-700 rounded text-xs"
                    >
                      ← 動画に戻る
                    </button>
                  </div>
                )
              }
              return (
                <Pass1RallyEnd
                  matchId={matchId ?? ''}
                  currentSet={currentSet}
                  rallies={mergedRallies}
                  pausedAtSec={pausedAtSec}
                  onRallyAdded={(r) => {
                    setLocalRallies((prev) => [...prev, r])
                    // 入力後は動画に戻す → 次のラリーへ視聴を続ける流れ
                    setScreen('play')
                  }}
                  onCancel={() => setScreen('play')}
                  onUndoLast={undefined /* TODO commit 6: enqueue DELETE */}
                  onSetEnded={() => {
                    // 次セットへ: 既存なら index 進める、なければ作成
                    if (currentSetIdx + 1 < allSets.length) {
                      setCurrentSetIdx(currentSetIdx + 1)
                    } else {
                      apiPost(`/sets`, {
                        match_id: Number(matchId),
                        set_num: (currentSet.set_num + 1),
                      }).then(() => {
                        setsQuery.refetch().then(() => {
                          setCurrentSetIdx(currentSetIdx + 1)
                        })
                      })
                    }
                  }}
                />
              )
            })()
          ) : (
            // Pass 2 / Pass 3 placeholder (後続 commit)
            <div className="flex-1 flex flex-col items-center justify-center text-gray-300 text-sm gap-3">
              <div>Pass <span className="font-mono text-blue-400">{pass}</span> (実装中)</div>
              <div className="text-xs text-gray-500">
                pausedAt = {pausedAtSec.toFixed(2)}s
              </div>
              <button
                type="button"
                onClick={() => setScreen('play')}
                className="px-3 py-1.5 bg-gray-700 rounded text-xs"
              >
                ← 動画に戻る
              </button>
            </div>
          )}
        </div>
      </div>
    </LandscapeGuard>
  )
}
