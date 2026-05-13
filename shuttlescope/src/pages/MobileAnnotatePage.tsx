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
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Play, Crosshair, Layers } from 'lucide-react'

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

  // body スクロール抑止: 全画面で固定
  useEffect(() => {
    const orig = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = orig
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

        {/* 本体: 後続 commit で動画 + 入力 overlay を入れる */}
        <div className="flex-1 flex items-center justify-center bg-gray-950">
          <div className="text-center text-gray-500 text-sm">
            {/* TODO commit 2: 動画再生 + クロップ + 下部コントロール */}
            scaffold ready — pass = <span className="font-mono text-blue-400">{pass}</span>
            <br />
            次の commit で動画再生 / クロップ / 入力 overlay を実装します。
          </div>
        </div>
      </div>
    </LandscapeGuard>
  )
}
