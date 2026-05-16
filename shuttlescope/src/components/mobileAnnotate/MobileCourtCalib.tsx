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

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 z-50"
      // 下層 (Pass1 set 1 prompt 等) が透けないよう不透明 0.92。動画フレームは
      // 編集中 pause しているので透ける必要はない。
      style={{ touchAction: 'none', background: 'rgba(0,0,0,0.92)' }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      onTouchCancel={onTouchEnd}
    >
      {/* SVG オーバーレイ: 既存点 + 結線 */}
      <svg
        className="absolute inset-0 pointer-events-none"
        width="100%"
        height="100%"
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

      {/* 下端ツールバー隠し toggle (BL/BR を画面最下端で置きたい時用)。
         隠した時も再表示できるよう、極小の chip だけは常時表示。 */}
      {toolbarHidden && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setToolbarHidden(false) }}
          onTouchStart={(e) => e.stopPropagation()}
          className="absolute z-10 px-2 py-1 rounded text-[10px] font-bold"
          style={{
            bottom: 'max(0.5rem, calc(env(safe-area-inset-bottom) + 0.5rem))',
            left: 'max(0.5rem, calc(env(safe-area-inset-left) + 0.5rem))',
            backgroundColor: 'rgba(0,0,0,0.85)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.5)',
          }}
        >
          ⊥ ツールバー再表示
        </button>
      )}
      {/* 下部操作 bar (safe-area-left/right 対応) */}
      {!toolbarHidden && (
      <div
        className="absolute z-10 flex items-center gap-2 px-2 py-1.5 rounded ss-overlay-chip"
        style={{
          bottom: 'max(0.5rem, calc(env(safe-area-inset-bottom) + 0.5rem))',
          left: 'max(0.5rem, calc(env(safe-area-inset-left) + 0.5rem))',
          right: 'max(0.5rem, calc(env(safe-area-inset-right) + 0.5rem))',
        }}
        onTouchStart={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={undo}
          disabled={points.length === 0 || saving}
          className="px-2 py-1.5 rounded text-xs font-bold"
          style={{
            backgroundColor: 'rgba(75,85,99,0.95)',
            color: '#ffffff',
            opacity: points.length === 0 ? 0.5 : 1,
            border: '1px solid rgba(255,255,255,0.2)',
          }}
        >
          ← 戻す
        </button>
        <button
          type="button"
          onClick={reset}
          disabled={points.length === 0 || saving}
          className="px-2 py-1.5 rounded text-xs font-bold"
          style={{
            backgroundColor: 'rgba(75,85,99,0.95)',
            color: '#ffffff',
            opacity: points.length === 0 ? 0.5 : 1,
            border: '1px solid rgba(255,255,255,0.2)',
          }}
        >
          全消去
        </button>
        <div className="flex-1 text-[10px] text-white/80 text-center">
          {err || (points.length === 6 ? '保存で desktop と共有' : '')}
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={saving}
          className="px-2 py-1.5 rounded text-xs font-bold"
          style={{
            backgroundColor: 'rgba(75,85,99,0.95)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.2)',
          }}
        >
          キャンセル
        </button>
        <button
          type="button"
          onClick={save}
          disabled={points.length !== 6 || saving}
          className="px-3 py-1.5 rounded text-xs text-white font-bold"
          style={{
            backgroundColor: points.length === 6 ? 'rgba(22,163,74,0.95)' : 'rgba(75,85,99,0.85)',
            opacity: points.length !== 6 || saving ? 0.5 : 1,
          }}
        >
          {saving ? '保存中…' : '保存'}
        </button>
        {/* ツールバー隠す toggle: コートの底辺ラインに点を置く時用 */}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setToolbarHidden(true) }}
          className="px-2 py-1.5 rounded text-xs font-bold"
          style={{
            backgroundColor: 'rgba(75,85,99,0.95)',
            color: '#ffffff',
            border: '1px solid rgba(255,255,255,0.2)',
          }}
          title="一時的に隠す (底辺点を置きやすくする)"
        >
          ⊥ 隠す
        </button>
      </div>
      )}
    </div>
  )
}
