/**
 * セッション共有モーダル — QRコード + URL表示
 */
import { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import { X, Copy, Check } from 'lucide-react'

interface Props {
  sessionCode: string
  coachUrls: string[]
  onClose: () => void
}

export function SessionShareModal({ sessionCode, coachUrls, onClose }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [copied, setCopied] = useState(false)
  const url = coachUrls[0] ?? ''

  useEffect(() => {
    if (!canvasRef.current || !url) return
    QRCode.toCanvas(canvasRef.current, url, {
      width: 220,
      margin: 2,
      color: { dark: '#0f172a', light: '#f8fafc' },
    }).catch(() => {})
  }, [url])

  const handleCopy = () => {
    navigator.clipboard.writeText(url).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-gray-800 border border-gray-700 rounded-xl shadow-2xl w-72 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ヘッダー */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-sm font-semibold text-white">セッション共有</p>
            <p className="text-xs text-gray-400 mt-0.5">
              コード:{' '}
              <span className="font-mono font-bold text-blue-300">{sessionCode}</span>
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={16} />
          </button>
        </div>

        {/* QRコード */}
        {url ? (
          <div className="flex justify-center mb-4 bg-slate-100 rounded-lg p-2">
            <canvas ref={canvasRef} />
          </div>
        ) : (
          <p className="text-xs text-gray-500 text-center mb-4">URLなし</p>
        )}

        {/* URL表示 + コピー */}
        {url && (
          <div className="flex items-center gap-1.5">
            <p className="flex-1 text-[10px] text-gray-400 font-mono truncate bg-gray-900/60 rounded px-2 py-1">
              {url}
            </p>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-500 text-white whitespace-nowrap"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? 'コピー済' : 'コピー'}
            </button>
          </div>
        )}

        <p className="text-[10px] text-gray-600 text-center mt-3">
          QRコードをスマホで読み取り、コーチ/共有ビューを開く
        </p>
      </div>
    </div>
  )
}
