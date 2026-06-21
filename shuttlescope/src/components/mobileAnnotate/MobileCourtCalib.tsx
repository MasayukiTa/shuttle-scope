/**
 * MobileCourtCalib — モバイル用コートキャリブレーション編集 (タッチ専用)
 *
 * デスクトップの CourtGridOverlay 編集と同等の機能をスマホサイズに最適化。
 *
 * 操作:
 *   1) 「TL (左上)」「TR (右上)」「BR (右下)」「BL (左下)」
 *      「NL (ネット左)」「NR (ネット右)」を順番にタップで設置
 *   2) 設置済みの点はドラッグで微調整可
 *   3) 6 点埋まったら「保存」で backend POST + localStorage
 *
 * 保存先:
 *   - POST /api/matches/{id}/court_calibration  (失敗しても localStorage は保存)
 *   - localStorage `court-calib-{matchId}` (desktop と共有)
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { apiPost } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'
import { useAutoTutorial } from '@/components/tutorial/useTutorial'
import { useTranslation } from 'react-i18next'

interface Pt { x: number; y: number }

interface Props {
  matchId: string | number
  initial: Pt[]                        // 既存の 6 点 (新規時は空配列)
  videoWidth: number
  videoHeight: number
  onClose: () => void                  // キャンセル / 保存後に呼ばれる
  onSaved: (pts: Pt[]) => void         // 親 (PlayMode 側) で再描画
  snapshot?: string | null             // ルーペ表示用 dataURL (動画 frame)
}

const HANDLE_R = 18  // タッチ判定半径 (px)

export function MobileCourtCalib({ matchId, initial, videoWidth, videoHeight, onClose, onSaved, snapshot }: Props) {
  const { t } = useTranslation()
  // 順番ラベル (TL, TR, BR, BL, NL, NR)。t() はコンポーネント内のみで参照する規約。
  const STEP_LABELS = useMemo(() => [
    t('auto.MobileCourtCalib.step_tl'),
    t('auto.MobileCourtCalib.step_tr'),
    t('auto.MobileCourtCalib.step_br'),
    t('auto.MobileCourtCalib.step_bl'),
    t('auto.MobileCourtCalib.step_nl'),
    t('auto.MobileCourtCalib.step_nr'),
  ], [t])
  // 初回キャリブ起動時にチュートリアルを自動再生 (指ルーペ操作・点位置の解説)
  useAutoTutorial('mobile_court_calibration')
  // 既存 6 点があれば初期表示、なければ空配列
  const [points, setPoints] = useState<Pt[]>(() => initial.length === 6 ? [...initial] : [])
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string>('')
  // 下端ツールバーを一時的に隠す (= コート底辺の点を BL/BR に置きたい時用)
  const [_toolbarHidden, _setToolbarHidden] = useState(false)
  // 初期で既存点が入った場合の「復元済み」インジケータを保持
  const [restoredFromExisting] = useState<boolean>(initial.length === 6)
  const containerRef = useRef<HTMLDivElement | null>(null)
  // 🩺 オンスクリーン診断テキスト (PWA で console 見えないため画面に出す)
  const [diag, setDiag] = useState<string>('')
  // ルーペ UX: 指で隠れる領域を画面上部に拡大表示する。
  // touchstart で表示開始、touchmove で位置更新、touchend で非表示。
  const [loupe, setLoupe] = useState<{ x: number; y: number } | null>(null)

  // 次に追加する点の index (0-5)。6 点埋まったら null。
  const nextIdx = points.length < 6 ? points.length : null

  // タッチ → 正規化座標 (0-1)
  const touchToNorm = (clientX: number, clientY: number): Pt | null => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || rect.height === 0) return null
    return {
      x: Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (clientY - rect.top) / rect.height)),
    }
  }

  // ハンドル ヒット判定 (タッチ半径 HANDLE_R 内に既存点があれば drag、無ければ tap-to-place)
  const hitHandle = (clientX: number, clientY: number): number | null => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return null
    for (let i = 0; i < points.length; i++) {
      const px = rect.left + points[i].x * rect.width
      const py = rect.top + points[i].y * rect.height
      const dx = clientX - px
      const dy = clientY - py
      if (dx * dx + dy * dy <= HANDLE_R * HANDLE_R) return i
    }
    return null
  }

  const onTouchStart = (e: React.TouchEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const t = e.touches[0]
    // 🩺 診断: タップ位置の element stack を dump。getComputedStyle を毎 touch で
    // 走らせると低スペック端末で同期レイアウトが発生し操作が重くなるため、本番では
    // 走らせない (DEV ビルドのみ)。import.meta.env.DEV は本番ビルドで static に false
    // となり、esbuild がブロックごと dead-code 除去する。
    if (import.meta.env.DEV) {
      try {
        const stack = document.elementsFromPoint(t.clientX, t.clientY)
        const desc = stack.slice(0, 5).map((el) => {
          const tag = el.tagName
          const cls = (el.className && typeof el.className === 'string')
            ? el.className.slice(0, 30) : ''
          const id = el.id ? `#${el.id}` : ''
          const cs = window.getComputedStyle(el)
          return `${tag}${id}.${cls}[z=${cs.zIndex},pe=${cs.pointerEvents}]`
        })
        // eslint-disable-next-line no-console
        console.log('[calib-tap]', `(${Math.round(t.clientX)},${Math.round(t.clientY)})`, desc)
        setDiag(
          `TAP(${Math.round(t.clientX)},${Math.round(t.clientY)}) ` +
          `pts=${points.length}/6 nextIdx=${nextIdx} ` +
          `vw=${videoWidth} vh=${videoHeight} ` +
          desc.slice(0, 2).join(' | '),
        )
      } catch { /* ignore */ }
    }
    // ルーペ表示開始
    setLoupe({ x: t.clientX, y: t.clientY })
    const hit = hitHandle(t.clientX, t.clientY)
    if (hit !== null) {
      setDragIdx(hit)
      return
    }
    if (nextIdx !== null) {
      const p = touchToNorm(t.clientX, t.clientY)
      if (p) setPoints((prev) => [...prev, p])
    }
  }

  const onTouchMove = (e: React.TouchEvent) => {
    const t = e.touches[0]
    if (!t) return
    // ルーペは指が動いている間は常に追従
    setLoupe({ x: t.clientX, y: t.clientY })
    if (dragIdx === null) return
    e.preventDefault()
    const p = touchToNorm(t.clientX, t.clientY)
    if (!p) return
    setPoints((prev) => {
      const next = [...prev]
      next[dragIdx] = p
      return next
    })
  }

  const onTouchEnd = () => {
    setDragIdx(null)
    // 指離したら少し残してから消す (= 配置位置の最終確認時間)
    setTimeout(() => setLoupe(null), 350)
  }

  const undo = () => {
    setPoints((prev) => prev.slice(0, -1))
  }

  const reset = () => {
    setPoints([])
  }

  const save = async () => {
    if (points.length !== 6) {
      setErr(t('auto.MobileCourtCalib.err_need_6'))
      return
    }
    setSaving(true)
    setErr('')
    // close 判定は state(err) ではなくローカル変数で行う。setErr は非同期で、
    // この closure の `err` は描画時の値('')のままなので、!err 判定だと
    // サーバ保存失敗時もバナーを見せず即 close してしまう (失敗の無言化)。
    let serverFailed = false
    try {
      const payload = { points: points.map((p) => [p.x, p.y] as [number, number]) }
      try {
        await apiPost(`/matches/${matchId}/court_calibration`, payload)
      } catch {
        // backend 失敗時も localStorage は保存して desktop と共有可能にする
        serverFailed = true
        setErr(t('auto.MobileCourtCalib.err_server_failed_local_only'))
      }
      try {
        localStorage.setItem(`court-calib-${matchId}`, JSON.stringify(points))
      } catch { /* ignore */ }
      onSaved(points)
      // サーバ保存に失敗していなければ閉じる (失敗時はバナーを見せて開いたまま)。
      if (!serverFailed) onClose()
    } finally {
      setSaving(false)
    }
  }

  // body スクロール抑止 (元の MobileAnnotatePage がやってるが二重に念のため)
  useEffect(() => {
    const orig = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = orig }
  }, [])

  // 🩺 document-level capture: React touchstart に来ない touch を確認する。
  // 「下 3/4 タップしても何も起きない」 = (A) touch 自体が来ていない (= 何かが
  // pre-react レベルで止めている) か、(B) touch は来ているが calib container
  // 以外がターゲット (= 透明何かが上に乗ってる) のいずれか。これで切り分け。
  useEffect(() => {
    if (!import.meta.env.DEV) return  // 本番ではデバッグ用 document リスナを張らない
    const onTouch = (ev: TouchEvent) => {
      const t = ev.touches[0]
      if (!t) return
      const tgt = ev.target as Element | null
      const W = window.innerWidth
      const H = window.innerHeight
      const tag = tgt?.tagName
      const cls = (tgt && typeof tgt.className === 'string')
        ? tgt.className.slice(0, 30) : ''
      setDiag(
        `DOC-TOUCH(${Math.round(t.clientX)},${Math.round(t.clientY)}) ` +
        `vp=${W}x${H} tgt=${tag}.${cls} ` +
        `pts=${points.length}/6`,
      )
    }
    document.addEventListener('touchstart', onTouch, true) // capture phase
    return () => document.removeEventListener('touchstart', onTouch, true)
  }, [points.length])

  // 🩺 診断: calib mount 直後に、viewport 中央/上下左右の各点に何が乗っているか
  // dump する。"透明な何かが center をブロック" 疑惑を即時確認する。
  useEffect(() => {
    if (!import.meta.env.DEV) return  // 本番では mount 時 center-probe を行わない
    const dump = () => {
      const W = window.innerWidth
      const H = window.innerHeight
      try {
        const stack = document.elementsFromPoint(W / 2, H / 2)
        const desc = stack.slice(0, 5).map((el) => {
          const tag = el.tagName
          const cls = (el.className && typeof el.className === 'string')
            ? el.className.slice(0, 30) : ''
          const id = el.id ? `#${el.id}` : ''
          const cs = window.getComputedStyle(el)
          return `${tag}${id}.${cls}[z=${cs.zIndex},pe=${cs.pointerEvents}]`
        })
        // eslint-disable-next-line no-console
        console.log('[calib-probe] center', desc)
        setDiag(`CENTER(${Math.round(W/2)},${Math.round(H/2)}) ` + desc.slice(0, 3).join(' | '))
      } catch { /* ignore */ }
    }
    // mount 直後 (paint 後) に dump
    const id = setTimeout(dump, 100)
    return () => clearTimeout(id)
  }, [])

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 z-50"
      // ⚠️ 編集中は動画が見えないと点が置けない。背景は薄い dim のみ。
      // Pass1 prompt 等が透けて見える事象は PlayMode 側で「calib 中は Pass1 を隠す」
      // (= MobileAnnotatePage で `!calibEditing &&` で gate) ことで構造的に防ぐ。
      style={{ touchAction: 'none', background: 'rgba(0,0,0,0.15)' }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchEnd}
    >
      {/* SVG オーバーレイ: 既存点 + 結線
         NOTE: width/height は **明示 px** (videoWidth x videoHeight) + viewBox 同値。
         width="100%" + viewBox では iOS Safari PWA で aspect 演算がぶれて
         描画位置がズレる事象あり。明示 px なら 1:1 mapping が必ず成立する。 */}
      <svg
        width={videoWidth}
        height={videoHeight}
        viewBox={`0 0 ${videoWidth} ${videoHeight}`}
        style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none' }}
      >
        {/* ネット線 (NL-NR があれば描画) */}
        {points.length >= 6 && (
          <line
            x1={points[4].x * videoWidth} y1={points[4].y * videoHeight}
            x2={points[5].x * videoWidth} y2={points[5].y * videoHeight}
            stroke="#f59e0b" strokeWidth={3} strokeDasharray="6,4"
          />
        )}
        {/* コート外周 (TL-TR-BR-BL があれば描画) */}
        {points.length >= 4 && (
          <polygon
            points={[0,1,2,3].map(i => `${points[i].x * videoWidth},${points[i].y * videoHeight}`).join(' ')}
            fill="none"
            stroke="#22c55e"
            strokeWidth={2}
          />
        )}
        {/* 各ハンドル */}
        {points.map((p, i) => {
          const cx = p.x * videoWidth
          const cy = p.y * videoHeight
          const isNet = i >= 4
          return (
            <g key={i}>
              <circle cx={cx} cy={cy} r={HANDLE_R} fill="rgba(0,0,0,0.5)" stroke={isNet ? '#f59e0b' : '#22c55e'} strokeWidth={2} />
              <circle cx={cx} cy={cy} r={4} fill={isNet ? '#f59e0b' : '#22c55e'} />
              <text x={cx + HANDLE_R + 4} y={cy + 4} fill="#fff" fontSize="11" fontFamily="monospace">
                {STEP_LABELS[i].split(' ')[0]}
              </text>
            </g>
          )
        })}
      </svg>

      {/* 上部ガイド bar (#ffffff 強制 — グレー背景に同色文字回避) */}
      <div
        className="absolute z-10 px-3 py-2 rounded text-xs font-bold"
        style={{
          top: 'max(0.5rem, calc(env(safe-area-inset-top) + 0.5rem))',
          left: 'max(0.5rem, calc(env(safe-area-inset-left) + 0.5rem))',
          right: 'max(0.5rem, calc(env(safe-area-inset-right) + 0.5rem))',
          color: '#ffffff',
          backgroundColor: 'rgba(37,99,235,0.95)',
          border: '1px solid rgba(255,255,255,0.3)',
        }}
      >
        {nextIdx !== null ? (
          <span style={{ color: '#ffffff' }}>
            <b style={{ color: '#ffffff' }}>{STEP_LABELS[nextIdx]}</b>{t('auto.MobileCourtCalib.tap_to_place_suffix', { n: points.length })}
            {restoredFromExisting && (
              <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '10px', marginLeft: 8 }}>
                {t('auto.MobileCourtCalib.restored', { n: initial.length })}
              </span>
            )}
          </span>
        ) : (
          <span style={{ color: '#ffffff' }}>
            {t('auto.MobileCourtCalib.all_placed')}
            {restoredFromExisting && (
              <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '10px', marginLeft: 8 }}>
                {t('auto.MobileCourtCalib.restored_short')}
              </span>
            )}
          </span>
        )}
      </div>

      {/* 操作ボタン: 画面右辺 縦並びアイコン (動画底辺をふさがない設計)。
         lucide → MIcon (Material Symbols) で規約遵守。 */}
      <div
        className="absolute z-10 flex flex-col gap-2 pointer-events-auto"
        style={{
          top: '50%',
          transform: 'translateY(-50%)',
          right: 'max(0.5rem, calc(env(safe-area-inset-right) + 0.5rem))',
        }}
        onTouchStart={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={undo}
          disabled={points.length === 0 || saving}
          title={t('auto.MobileCourtCalib.k1')}
          className="rounded-full"
          style={{
            width: 44, height: 44,
            backgroundColor: 'rgba(0,0,0,0.85)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.4)',
            opacity: points.length === 0 ? 0.35 : 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <MIcon name="undo" size={20} style={{ color: '#ffffff' }} />
        </button>
        <button
          type="button"
          onClick={reset}
          disabled={points.length === 0 || saving}
          title={t('auto.MobileCourtCalib.k2')}
          className="rounded-full"
          style={{
            width: 44, height: 44,
            backgroundColor: 'rgba(0,0,0,0.85)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.4)',
            opacity: points.length === 0 ? 0.35 : 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <MIcon name="delete_sweep" size={20} style={{ color: '#ffffff' }} />
        </button>
        <button
          type="button"
          onClick={save}
          disabled={points.length !== 6 || saving}
          title={points.length === 6 ? t('auto.MobileCourtCalib.save_title_ready') : t('auto.MobileCourtCalib.save_title_need_6')}
          className="rounded-full"
          style={{
            width: 48, height: 48,
            backgroundColor: points.length === 6 ? 'rgba(22,163,74,0.98)' : 'rgba(0,0,0,0.6)',
            color: '#ffffff',
            border: '2px solid #ffffff',
            opacity: points.length !== 6 || saving ? 0.5 : 1,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <MIcon name={saving ? 'hourglass_top' : 'check'} size={22} style={{ color: '#ffffff' }} />
        </button>
        <button
          type="button"
          onClick={onClose}
          disabled={saving}
          title={t('auto.MobileCourtCalib.k3')}
          className="rounded-full"
          style={{
            width: 44, height: 44,
            backgroundColor: 'rgba(0,0,0,0.85)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <MIcon name="close" size={20} style={{ color: '#ffffff' }} />
        </button>
      </div>

      {/* ルーペ: 指の真下を拡大表示 (画面上端中央)。
         旧実装は背景画像で snapshot を videoWidth×videoHeight 比に強制
         stretch していたため、native aspect (16:9) と container aspect
         (例 2.16:1) が違うと水平方向にズレた。
         新実装: ルーペ内に同サイズの <img objectFit:cover> ステージを置き、
         CSS transform で zoom + 指位置 (X, Y) を中央 (66, 66) に持ってくる。
         これで snapshot 表示と underlying video 表示が完全一致する。 */}
      {loupe && (() => {
        const zoom = 2.2
        const size = 132
        const half = size / 2
        // 指から離した位置: 上端中央が基本。指が上端付近 (~ルーペ+余白) なら下端へ逃げる。
        const loupeTop = loupe.y < size + 60 ? undefined : 24
        const loupeBottom = loupe.y < size + 60 ? 24 : undefined
        return (
          <div
            className="absolute pointer-events-none"
            style={{
              ...(loupeTop !== undefined ? { top: loupeTop } : { bottom: loupeBottom }),
              left: '50%',
              marginLeft: -half,
              width: size,
              height: size,
              borderRadius: '50%',
              border: '3px solid #ffffff',
              boxShadow: '0 4px 12px rgba(0,0,0,0.6)',
              backgroundColor: 'rgba(20,20,20,0.85)',
              zIndex: 20,
              overflow: 'hidden',
            }}
          >
            {/* snapshot は container サイズ (videoWidth×videoHeight) で cover-fit
               焼き付け済 → 1 snapshot px = 1 container px。img は **native サイズ**
               (= width:videoWidth, height:videoHeight) で配置し、transform scale で
               拡大。touch (X, Y) を中央 (half, half) に持ってくる left/top 計算: */}
            {snapshot && (
              <img
                src={snapshot}
                alt=""
                draggable={false}
                style={{
                  position: 'absolute',
                  width: videoWidth,
                  height: videoHeight,
                  left: half - loupe.x * zoom,
                  top: half - loupe.y * zoom,
                  transform: `scale(${zoom})`,
                  transformOrigin: '0 0',
                  display: 'block',
                }}
              />
            )}
            {/* 十字 (中央 = 指の真下 = 配置位置) */}
            <div
              style={{
                position: 'absolute', left: '50%', top: 0, bottom: 0,
                width: 1, marginLeft: -0.5,
                background: 'rgba(255,255,255,0.85)',
              }}
            />
            <div
              style={{
                position: 'absolute', top: '50%', left: 0, right: 0,
                height: 1, marginTop: -0.5,
                background: 'rgba(255,255,255,0.85)',
              }}
            />
            {/* 中心の小さい円 (= 配置確定位置) */}
            <div
              style={{
                position: 'absolute', left: '50%', top: '50%',
                width: 10, height: 10, marginLeft: -5, marginTop: -5,
                borderRadius: '50%',
                border: '2px solid #22c55e',
                background: 'rgba(34,197,94,0.3)',
              }}
            />
          </div>
        )
      })()}

      {/* オンスクリーン診断 (中央 element stack / 最終 tap 位置の stack)。本番では非表示。 */}
      {import.meta.env.DEV && diag && (
        <div
          className="absolute z-10 px-2 py-1 rounded text-[9px] font-mono pointer-events-none"
          style={{
            bottom: 'max(0.5rem, calc(env(safe-area-inset-bottom) + 0.5rem))',
            left: 'max(0.5rem, calc(env(safe-area-inset-left) + 0.5rem))',
            right: 'max(4rem, calc(env(safe-area-inset-right) + 4rem))',
            backgroundColor: 'rgba(0,0,0,0.85)',
            color: '#ffe066',
            border: '1px solid rgba(255,255,255,0.3)',
            wordBreak: 'break-all',
            maxHeight: '30vh',
            overflow: 'auto',
          }}
        >
          {diag}
        </div>
      )}

      {/* エラー banner (出ても OK な位置に最小限) */}
      {err && (
        <div
          className="absolute z-10 px-3 py-1.5 rounded text-[11px] font-bold"
          style={{
            bottom: 'max(0.5rem, calc(env(safe-area-inset-bottom) + 0.5rem))',
            left: 'max(0.5rem, calc(env(safe-area-inset-left) + 0.5rem))',
            right: 'max(4rem, calc(env(safe-area-inset-right) + 4rem))',
            backgroundColor: 'rgba(127,29,29,0.95)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.4)',
          }}
        >
          {err}
        </div>
      )}
    </div>
  )
}
