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
import { useEffect, useRef, useState } from 'react'
import { apiPost } from '@/api/client'
import { MIcon } from '@/components/common/MIcon'

interface Pt { x: number; y: number }

interface Props {
  matchId: string | number
  initial: Pt[]                        // 既存の 6 点 (新規時は空配列)
  videoWidth: number
  videoHeight: number
  onClose: () => void                  // キャンセル / 保存後に呼ばれる
  onSaved: (pts: Pt[]) => void         // 親 (PlayMode 側) で再描画
}

// 順番ラベル (TL, TR, BR, BL, NL, NR)
const STEP_LABELS = ['TL 左上', 'TR 右上', 'BR 右下', 'BL 左下', 'NL ネット左', 'NR ネット右']
const HANDLE_R = 18  // タッチ判定半径 (px)

export function MobileCourtCalib({ matchId, initial, videoWidth, videoHeight, onClose, onSaved }: Props) {
  // 既存 6 点があれば初期表示、なければ空配列
  const [points, setPoints] = useState<Pt[]>(() => initial.length === 6 ? [...initial] : [])
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string>('')
  // 下端ツールバーを一時的に隠す (= コート底辺の点を BL/BR に置きたい時用)
  const [toolbarHidden, setToolbarHidden] = useState(false)
  // 初期で既存点が入った場合の「復元済み」インジケータを保持
  const [restoredFromExisting] = useState<boolean>(initial.length === 6)
  const containerRef = useRef<HTMLDivElement | null>(null)
  // 🩺 オンスクリーン診断テキスト (PWA で console 見えないため画面に出す)
  const [diag, setDiag] = useState<string>('')

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
    // 🩺 診断: タップ位置にスタックされている全 element を console に dump。
    // 「中央が反応しない / 透明な何かが上に乗っている」疑惑を DOM レベルで検証する。
    // PWA 実機で Safari Web Inspector に繋いで確認する。
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
    if (dragIdx === null) return
    e.preventDefault()
    const t = e.touches[0]
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
  }

  const undo = () => {
    setPoints((prev) => prev.slice(0, -1))
  }

  const reset = () => {
    setPoints([])
  }

  const save = async () => {
    if (points.length !== 6) {
      setErr('6 点全て設置してから保存できます')
      return
    }
    setSaving(true)
    setErr('')
    try {
      const payload = { points: points.map((p) => [p.x, p.y] as [number, number]) }
      try {
        await apiPost(`/matches/${matchId}/court_calibration`, payload)
      } catch (_e) {
        // backend 失敗時も localStorage は保存して desktop と共有可能にする
        setErr('サーバ保存失敗 — ローカルのみ保存しました')
      }
      try {
        localStorage.setItem(`court-calib-${matchId}`, JSON.stringify(points))
      } catch { /* ignore */ }
      onSaved(points)
      // err が出てなければ close
      if (!err) onClose()
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
         ⚠️ viewBox を明示 (= videoWidth x videoHeight)。
         iOS Safari は viewBox 無し + width/height=100% の SVG で coordinate
         system を intrinsic 300x150 に縮退させる既知バグがあり、cy>150 の
         描画が消える (= 画面下 3/4 のハンドルが見えない症状)。
         viewBox を渡せば SVG ユーザ空間 (px) = videoWidth×videoHeight に
         固定される。preserveAspectRatio="none" で素直に伸縮させる。 */}
      <svg
        className="absolute inset-0 pointer-events-none"
        width="100%"
        height="100%"
        viewBox={`0 0 ${videoWidth} ${videoHeight}`}
        preserveAspectRatio="none"
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
            <b style={{ color: '#ffffff' }}>{STEP_LABELS[nextIdx]}</b> をタップで設置 ({points.length}/6)
            {restoredFromExisting && (
              <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '10px', marginLeft: 8 }}>
                / 前回セッションから {initial.length} 点復元済 (調整して保存 or 全消去)
              </span>
            )}
          </span>
        ) : (
          <span style={{ color: '#ffffff' }}>
            全 6 点設置完了。ハンドルをドラッグで微調整 → 保存
            {restoredFromExisting && (
              <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '10px', marginLeft: 8 }}>
                (前回セッションから復元)
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
          title="直前 1 点を戻す"
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
          title="全消去"
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
          title={points.length === 6 ? '保存 (desktop と共有)' : '6 点設置で有効化'}
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
          title="キャンセル"
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

      {/* 🩺 オンスクリーン診断 (中央 element stack / 最終 tap 位置の stack) */}
      {diag && (
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
