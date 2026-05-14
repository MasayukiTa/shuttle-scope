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
import { ArrowLeft, Play, Crosshair, Layers, CloudOff, AlertTriangle, RotateCw, Maximize2, Smartphone } from 'lucide-react'
import { apiGet, apiPost } from '@/api/client'
import { getMobileVideoSrc } from '@/utils/videoSrc'
import { PlayMode } from '@/components/mobileAnnotate/PlayMode'
import { Pass1RallyEnd } from '@/components/mobileAnnotate/Pass1RallyEnd'
import { Pass2ServeFinal } from '@/components/mobileAnnotate/Pass2ServeFinal'
import { Pass3ShotDetail } from '@/components/mobileAnnotate/Pass3ShotDetail'
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
    // インライン style で確実に白を適用 (Tailwind purge / dark-mode 変数の予期せぬ
    // 上書きで暗くなる事象を抑制する。lucide-react は stroke=currentColor なので
    // 親 color が白なら icon も白になる。)
    return (
      <div
        className="fixed inset-0 z-50 flex flex-col items-center justify-center p-6 text-center"
        style={{ backgroundColor: '#000000', color: '#ffffff' }}
      >
        <div className="relative mb-4" style={{ color: '#ffffff' }}>
          <Smartphone size={64} strokeWidth={1.5} style={{ color: '#ffffff', stroke: '#ffffff' }} />
          <RotateCw
            className="absolute -top-3 -right-3"
            size={28}
            strokeWidth={2}
            style={{ color: '#ffffff', stroke: '#ffffff' }}
          />
        </div>
        <h2 className="text-xl font-bold mb-2" style={{ color: '#ffffff' }}>端末を横向きに</h2>
        <p className="text-sm" style={{ color: 'rgba(255,255,255,0.9)' }}>
          スマホアノテーションは横向き専用です。<br />
          端末を回転させてください。
        </p>
        <p className="text-[11px] mt-6 max-w-xs" style={{ color: 'rgba(255,255,255,0.6)' }}>
          Safari でアドレスバーが邪魔な場合は、<br />
          画面下から上にスワイプすると一時的に隠れます。<br />
          長期的にはホーム画面に追加 (aA → 共有 → 「ホーム画面に追加」) で
          フルスクリーン化を推奨。
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
  const videoSrc = getMobileVideoSrc(match)

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

  // body スクロール抑止 + iOS Safari URL バー minimize
  useEffect(() => {
    const origBodyOverflow = document.body.style.overflow
    const origHtmlOverflow = document.documentElement.style.overflow
    const origHtmlHeight = document.documentElement.style.height
    document.body.style.overflow = 'hidden'
    document.documentElement.style.overflow = 'hidden'
    // iOS Safari: html 高さを 100vh + 1px にして 1 度だけ scroll させると
    // 上部 URL バーが minimize される
    document.documentElement.style.height = '100vh'
    // 微小 scroll trick (iOS Safari の上部 URL バー / 下部タブバーを minimize)
    window.scrollTo(0, 1)
    return () => {
      document.body.style.overflow = origBodyOverflow
      document.documentElement.style.overflow = origHtmlOverflow
      document.documentElement.style.height = origHtmlHeight
    }
  }, [])

  // フルスクリーン API (iOS Safari は video element に対してのみ可)
  // 任意のタイミングでユーザがタップして full screen に入れるよう関数を用意
  const requestVideoFullscreen = () => {
    const v = videoElRef.current
    if (!v) return
    const anyV = v as any
    if (anyV.webkitEnterFullscreen) anyV.webkitEnterFullscreen()
    else if (v.requestFullscreen) v.requestFullscreen().catch(() => {})
  }

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
      <div className="fixed inset-0 bg-black text-white touch-none select-none">
        {/* 本体: viewport 全面に動画 / アノテ画面が広がる */}
        <div className="absolute inset-0 bg-gray-950">
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
                  onUndoLast={async () => {
                    // 直前ラリーの Undo: server id があれば DELETE queue、
                    // 無ければ local state からのみ削除。
                    if (!currentSet) return
                    const setRallies = mergedRallies.filter((r) => r.set_id === currentSet.id)
                    const last = setRallies[setRallies.length - 1]
                    if (!last) return
                    if (last.id) {
                      const { enqueue } = await import('@/utils/mobileAnnotateQueue')
                      await enqueue('DELETE /api/rallies/:id', undefined, { id: last.id })
                      // optimistic: 一覧から消し、server fetch も refresh
                      setLocalRallies((prev) => prev.filter(
                        (r) => !(r.set_id === last.set_id && r.rally_num === last.rally_num),
                      ))
                      ralliesQuery.refetch()
                    } else {
                      // local pending のみ → state から除外で完了
                      setLocalRallies((prev) =>
                        prev.filter((r) => r.client_uuid !== last.client_uuid),
                      )
                    }
                  }}
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
          ) : pass === 'serve_final' ? (
            // Pass 2: 該当ラリーを picker で選んで 4-step に入る
            <Pass2RallyPicker
              rallies={mergedRallies}
              sets={allSets}
              pausedAtSec={pausedAtSec}
              onCancel={() => setScreen('play')}
            />
          ) : (
            // Pass 3: ラリー選択 → ショット詳細
            <Pass3RallyPicker
              matchId={matchId ?? ''}
              rallies={mergedRallies}
              sets={allSets}
              pausedAtSec={pausedAtSec}
              onCancel={() => setScreen('play')}
            />
          )}
        </div>

        {/* 左上オーバーレイ: 戻る + match #id + キュー (白基調) */}
        <div
          className="absolute left-2 z-30 flex items-center gap-1.5 text-xs"
          style={{ top: 'max(0.5rem, env(safe-area-inset-top))' }}
        >
          <button
            type="button"
            onClick={() => navigate('/matches')}
            className="p-2 rounded shadow"
            style={{ backgroundColor: 'rgba(255,255,255,0.95)', color: '#0f172a' }}
            aria-label="戻る"
          >
            <ArrowLeft size={16} />
          </button>
          <span
            className="font-mono text-[10px] px-1.5 py-1 rounded shadow"
            style={{ backgroundColor: 'rgba(255,255,255,0.9)', color: '#0f172a' }}
          >
            #{matchId ?? '?'}
          </span>
          {queueStatus.pending > 0 && (
            <span
              className="flex items-center gap-1 text-[10px] px-1.5 py-1 rounded shadow"
              style={{ backgroundColor: 'rgba(254,243,199,0.95)', color: '#92400e' }}
              title={`未送信 ${queueStatus.pending} 件 (再送中)`}
            >
              <CloudOff size={12} />
              {queueStatus.pending}
            </span>
          )}
          {queueStatus.manualRetry > 0 && (
            <button
              type="button"
              onClick={() => void retryAllManual()}
              className="flex items-center gap-1 text-[10px] px-1.5 py-1 rounded shadow"
              style={{ backgroundColor: 'rgba(254,226,226,0.95)', color: '#991b1b', border: '1px solid #fca5a5' }}
              title={`送信失敗 ${queueStatus.manualRetry} 件 — タップで再送`}
            >
              <AlertTriangle size={12} />
              {queueStatus.manualRetry}
            </button>
          )}
        </div>

        {/* 右側中央オーバーレイ: Pass 切替 (白チップ + 橙アクセント) */}
        <div
          className="absolute right-2 z-30 flex flex-col gap-1.5"
          style={{ top: '50%', transform: 'translateY(-50%)' }}
        >
          {(Object.keys(PASS_LABELS) as AnnotatePass[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPass(p)}
              className="flex items-center gap-1 px-2 py-1.5 rounded text-[10px] font-medium shadow"
              style={{
                backgroundColor: pass === p ? 'rgba(245,158,11,0.98)' : 'rgba(255,255,255,0.95)',
                color: pass === p ? '#ffffff' : '#0f172a',
              }}
              title={PASS_LABELS[p]}
            >
              {PASS_ICONS[p]}
              <span className="hidden xs:inline">{PASS_LABELS[p]}</span>
            </button>
          ))}
        </div>
      </div>
    </LandscapeGuard>
  )
}


/**
 * Pass 2 のラリー picker。pausedAtSec 付近のラリーから順にリスト表示し、
 * 選択するとそのラリーに対する Pass2ServeFinal step machine を起動する。
 */
function Pass2RallyPicker({
  rallies,
  sets,
  pausedAtSec,
  onCancel,
}: {
  rallies: RallyLite[]
  sets: SetInfo[]
  pausedAtSec: number
  onCancel: () => void
}) {
  const [selected, setSelected] = useState<RallyLite | null>(null)

  // pausedAtSec に近い順
  const sortedRallies = useMemo(() => {
    return [...rallies].sort((a, b) => {
      const da = Math.abs((a.video_timestamp_end ?? 0) - pausedAtSec)
      const db = Math.abs((b.video_timestamp_end ?? 0) - pausedAtSec)
      return da - db
    })
  }, [rallies, pausedAtSec])

  if (selected) {
    const setInfo = sets.find((s) => s.id === selected.set_id)
    if (!setInfo || !selected.id) {
      // ローカル pending (まだサーバ id がない) なら入れない
      return (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-300 text-sm gap-3 p-4">
          <div className="text-center">
            このラリーはまだサーバ保存中です。
            <br />
            送信完了後に Pass 2 入力を行えます。
          </div>
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="px-3 py-1.5 bg-gray-700 rounded text-xs"
          >
            ← 一覧に戻る
          </button>
        </div>
      )
    }
    return (
      <Pass2ServeFinal
        rally={{
          id: selected.id,
          rally_num: selected.rally_num,
          set_num: setInfo.set_num,
          server: selected.server,
          winner: selected.winner,
        }}
        onCompleted={() => setSelected(null)}
        onCancel={() => setSelected(null)}
      />
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-black/90">
      <div className="px-3 py-2 border-b border-gray-800 text-xs text-yellow-200">
        Pass 2 入力するラリーを選択 (タップ位置 @{pausedAtSec.toFixed(1)}s に近い順)
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sortedRallies.length === 0 ? (
          <div className="text-gray-500 text-center text-sm py-8">
            Pass 1 でラリーを記録してから戻ってきてください
          </div>
        ) : (
          sortedRallies.map((r) => {
            const setInfo = sets.find((s) => s.id === r.set_id)
            return (
              <button
                key={`${r.set_id}-${r.rally_num}`}
                type="button"
                onClick={() => setSelected(r)}
                className="w-full text-left px-3 py-2 rounded bg-gray-800 hover:bg-gray-700 flex items-center gap-3"
              >
                <span className="font-mono text-[11px] text-gray-400">
                  S{setInfo?.set_num ?? '?'}-R{r.rally_num}
                </span>
                <span className="font-mono text-xs">
                  <span className={r.winner === 'player_a' ? 'text-blue-400' : 'text-pink-400'}>
                    {r.winner === 'player_a' ? 'A' : 'B'} 得点
                  </span>
                </span>
                <span className="text-[11px] text-gray-500">
                  {r.score_a_after}-{r.score_b_after}
                </span>
                <div className="flex-1" />
                <span className="font-mono text-[10px] text-gray-500">
                  @{(r.video_timestamp_end ?? 0).toFixed(1)}s
                </span>
                {r.pending && (
                  <span className="text-[10px] text-amber-400">pending</span>
                )}
              </button>
            )
          })
        )}
      </div>
      <div className="px-3 py-2 border-t border-gray-800">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded bg-gray-700 text-white text-xs"
        >
          ← 動画に戻る
        </button>
      </div>
    </div>
  )
}


/**
 * Pass 3 のラリー picker。選択するとそのラリーの strokes を fetch して
 * Pass3ShotDetail を起動。
 */
function Pass3RallyPicker({
  matchId,
  rallies,
  sets,
  pausedAtSec,
  onCancel,
}: {
  matchId: string
  rallies: RallyLite[]
  sets: SetInfo[]
  pausedAtSec: number
  onCancel: () => void
}) {
  const [selected, setSelected] = useState<RallyLite | null>(null)
  const [localStrokes, setLocalStrokes] = useState<Array<{
    id?: number | null
    rally_id: number
    stroke_num: number
    player: 'player_a' | 'player_b'
    shot_type: string
    hit_zone?: string | null
    land_zone?: string | null
    pending?: boolean
  }>>([])

  // 選択ラリーの stroke を fetch
  const strokesQuery = useQuery({
    queryKey: ['mobile-annot-strokes', selected?.id],
    queryFn: () => apiGet<{ data: any[] }>(`/strokes?rally_id=${selected!.id}`),
    enabled: !!selected?.id,
  })

  const sortedRallies = useMemo(() => {
    return [...rallies].sort((a, b) => {
      const da = Math.abs((a.video_timestamp_end ?? 0) - pausedAtSec)
      const db = Math.abs((b.video_timestamp_end ?? 0) - pausedAtSec)
      return da - db
    })
  }, [rallies, pausedAtSec])

  if (selected) {
    if (!selected.id) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-300 text-sm gap-3 p-4">
          <div className="text-center">
            このラリーはまだサーバ保存中です。送信完了後に Pass 3 入力を行えます。
          </div>
          <button
            type="button"
            onClick={() => setSelected(null)}
            className="px-3 py-1.5 bg-gray-700 rounded text-xs"
          >
            ← 一覧に戻る
          </button>
        </div>
      )
    }
    const setInfo = sets.find((s) => s.id === selected.set_id)
    const serverStrokes = (strokesQuery.data?.data ?? []).map((s: any) => ({
      id: s.id,
      rally_id: s.rally_id,
      stroke_num: s.stroke_num,
      player: s.player,
      shot_type: s.shot_type,
      hit_zone: s.hit_zone,
      land_zone: s.land_zone,
      pending: false,
    }))
    const local = localStrokes.filter((s) => s.rally_id === selected.id)
    const all = [...serverStrokes, ...local]
    return (
      <Pass3ShotDetail
        rally={{
          id: selected.id,
          rally_num: selected.rally_num,
          set_num: setInfo?.set_num ?? 1,
          server: selected.server,
          winner: selected.winner,
        }}
        strokes={all}
        onStrokeAdded={(s) => {
          setLocalStrokes((prev) => [...prev, { ...s, rally_id: selected.id! }])
        }}
        onStrokeUpdated={(s) => {
          setLocalStrokes((prev) =>
            prev.map((x) =>
              x.rally_id === selected.id! && x.stroke_num === s.stroke_num
                ? { ...x, shot_type: s.shot_type }
                : x,
            ),
          )
        }}
        onClose={() => {
          setSelected(null)
          setLocalStrokes([])
        }}
      />
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-black/90">
      <div className="px-3 py-2 border-b border-gray-800 text-xs text-yellow-200">
        Pass 3 入力するラリーを選択
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sortedRallies.length === 0 ? (
          <div className="text-gray-500 text-center text-sm py-8">
            Pass 1 でラリーを記録してから戻ってきてください
          </div>
        ) : (
          sortedRallies.map((r) => {
            const setInfo = sets.find((s) => s.id === r.set_id)
            return (
              <button
                key={`${r.set_id}-${r.rally_num}`}
                type="button"
                onClick={() => setSelected(r)}
                className="w-full text-left px-3 py-2 rounded bg-gray-800 hover:bg-gray-700 flex items-center gap-3"
              >
                <span className="font-mono text-[11px] text-gray-400">
                  S{setInfo?.set_num ?? '?'}-R{r.rally_num}
                </span>
                <span className={r.winner === 'player_a' ? 'text-blue-400 text-xs' : 'text-pink-400 text-xs'}>
                  {r.winner === 'player_a' ? 'A 得点' : 'B 得点'}
                </span>
                <div className="flex-1" />
                <span className="font-mono text-[10px] text-gray-500">
                  @{(r.video_timestamp_end ?? 0).toFixed(1)}s
                </span>
              </button>
            )
          })
        )}
      </div>
      <div className="px-3 py-2 border-t border-gray-800">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded bg-gray-700 text-white text-xs"
        >
          ← 動画に戻る
        </button>
      </div>
    </div>
  )
}
