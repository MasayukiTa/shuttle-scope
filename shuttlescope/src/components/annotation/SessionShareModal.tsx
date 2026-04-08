/**
 * セッション共有モーダル — QRコード + URL表示 + パスワード管理
 */
import { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import { X, Copy, Check, Eye, EyeOff, RefreshCw, Camera } from 'lucide-react'
import { useIsLightMode } from '@/hooks/useIsLightMode'
import { useTranslation } from 'react-i18next'
import { apiPost } from '@/api/client'

interface Props {
  sessionCode: string
  coachUrls: string[]
  cameraSenderUrls?: string[]
  sessionPassword?: string
  onClose: () => void
}

export function SessionShareModal({
  sessionCode,
  coachUrls,
  cameraSenderUrls = [],
  sessionPassword: initialPassword,
  onClose,
}: Props) {
  const { t } = useTranslation()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const cameraCanvasRef = useRef<HTMLCanvasElement>(null)
  const [copied, setCopied] = useState(false)
  const [passwordCopied, setPasswordCopied] = useState(false)
  const [cameraUrlCopied, setCameraUrlCopied] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [sessionPassword, setSessionPassword] = useState(initialPassword ?? '')
  const [regenerating, setRegenerating] = useState(false)
  const isLight = useIsLightMode()

  const coachUrl = coachUrls[0] ?? ''
  const cameraUrl = cameraSenderUrls[0] ?? ''
  // パスワードを URL に埋め込む — LAN QR スキャン時にフォーム入力不要にする
  const cameraUrlWithPwd = cameraUrl && sessionPassword
    ? `${cameraUrl}?pwd=${encodeURIComponent(sessionPassword)}`
    : cameraUrl

  // コーチ URL の QR
  useEffect(() => {
    if (!canvasRef.current || !coachUrl) return
    QRCode.toCanvas(canvasRef.current, coachUrl, {
      width: 180,
      margin: 2,
      color: { dark: '#0f172a', light: '#f8fafc' },
    }).catch(() => {})
  }, [coachUrl])

  // カメラ送信 URL の QR（パスワード付き）
  useEffect(() => {
    if (!cameraCanvasRef.current || !cameraUrlWithPwd) return
    QRCode.toCanvas(cameraCanvasRef.current, cameraUrlWithPwd, {
      width: 180,
      margin: 2,
      color: { dark: '#0f172a', light: '#f8fafc' },
    }).catch(() => {})
  }, [cameraUrlWithPwd])

  const handleCopy = (text: string, setter: (v: boolean) => void) => {
    const confirm = () => { setter(true); setTimeout(() => setter(false), 2000) }
    const fallback = () => {
      try {
        const el = document.createElement('textarea')
        el.value = text
        el.style.cssText = 'position:fixed;top:0;left:0;opacity:0'
        document.body.appendChild(el)
        el.select()
        document.execCommand('copy')
        document.body.removeChild(el)
        confirm()
      } catch { /* コピー失敗は無視 */ }
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(confirm).catch(fallback)
    } else {
      fallback()
    }
  }

  const handleRegeneratePassword = async () => {
    setRegenerating(true)
    try {
      const res = await apiPost<{ success: boolean; data: { session_password: string } }>(
        `/sessions/${sessionCode}/regenerate-password`, {}
      )
      if (res.success) {
        setSessionPassword(res.data.session_password)
      }
    } catch {
      // 再生成失敗は無視
    } finally {
      setRegenerating(false)
    }
  }

  const panelBg = isLight ? 'bg-white border border-gray-200 shadow-xl' : 'bg-gray-800 border border-gray-700 shadow-2xl'
  const titleColor = isLight ? 'text-gray-900' : 'text-white'
  const subColor = isLight ? 'text-gray-500' : 'text-gray-400'
  const codeColor = isLight ? 'text-blue-600' : 'text-blue-300'
  const urlBg = isLight ? 'bg-gray-100' : 'bg-gray-900/60'
  const urlColor = isLight ? 'text-gray-600' : 'text-gray-400'
  const noteColor = isLight ? 'text-gray-400' : 'text-gray-600'
  const dividerColor = isLight ? 'border-gray-200' : 'border-gray-700'
  const sectionTitle = isLight ? 'text-gray-700 font-medium' : 'text-gray-300 font-medium'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className={`rounded-xl w-80 p-5 max-h-[90vh] overflow-y-auto ${panelBg}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ヘッダー */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className={`text-sm font-semibold ${titleColor}`}>セッション共有</p>
            <p className={`text-xs mt-0.5 ${subColor}`}>
              コード:{' '}
              <span className={`font-mono font-bold ${codeColor}`}>{sessionCode}</span>
            </p>
          </div>
          <button onClick={onClose} className={`${subColor} hover:${titleColor}`}>
            <X size={16} />
          </button>
        </div>

        {/* ─── コーチ URL / QR ─────────────────── */}
        <p className={`text-xs mb-2 ${sectionTitle}`}>コーチビュー</p>
        {coachUrl ? (
          <div className="flex justify-center mb-3 bg-slate-100 rounded-lg p-2">
            <canvas ref={canvasRef} />
          </div>
        ) : (
          <p className={`text-xs text-center mb-3 ${noteColor}`}>URLなし</p>
        )}
        {coachUrl && (
          <div className="flex items-center gap-1.5 mb-4">
            <p className={`flex-1 text-[10px] font-mono truncate rounded px-2 py-1 ${urlBg} ${urlColor}`}>
              {coachUrl}
            </p>
            <button
              onClick={() => handleCopy(coachUrl, setCopied)}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-500 text-white whitespace-nowrap"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? 'コピー済' : t('lan_session.password_copy')}
            </button>
          </div>
        )}

        {/* ─── パスワード ────────────────────── */}
        <div className={`border-t pt-4 mb-4 ${dividerColor}`}>
          <p className={`text-xs mb-2 ${sectionTitle}`}>{t('lan_session.password_label')}</p>
          <div className="flex items-center gap-1.5">
            <div className={`flex-1 flex items-center gap-1 rounded px-2 py-1 ${urlBg}`}>
              <span className={`flex-1 text-xs font-mono ${urlColor}`}>
                {sessionPassword
                  ? showPassword ? sessionPassword : '••••••••'
                  : <span className={noteColor}>未設定</span>
                }
              </span>
              {sessionPassword && (
                <button
                  onClick={() => setShowPassword((v) => !v)}
                  className={`${subColor} hover:${titleColor}`}
                >
                  {showPassword ? <EyeOff size={12} /> : <Eye size={12} />}
                </button>
              )}
            </div>
            {sessionPassword && (
              <button
                onClick={() => handleCopy(sessionPassword, setPasswordCopied)}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-500 text-white whitespace-nowrap"
              >
                {passwordCopied ? <Check size={12} /> : <Copy size={12} />}
                {passwordCopied ? 'コピー済' : t('lan_session.password_copy')}
              </button>
            )}
            <button
              onClick={handleRegeneratePassword}
              disabled={regenerating}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-amber-600 hover:bg-amber-500 text-white whitespace-nowrap disabled:opacity-50"
            >
              <RefreshCw size={12} className={regenerating ? 'animate-spin' : ''} />
              {t('lan_session.password_regenerate')}
            </button>
          </div>
          <p className={`text-[10px] mt-1 ${noteColor}`}>
            参加デバイスはセッションコードとパスワードの両方が必要です
          </p>
        </div>

        {/* ─── カメラ送信 URL / QR ─────────────── */}
        {cameraUrl && (
          <div className={`border-t pt-4 ${dividerColor}`}>
            <div className="flex items-center gap-1.5 mb-2">
              <Camera size={12} className={subColor} />
              <p className={`text-xs ${sectionTitle}`}>{t('lan_session.camera_sender_url_label')}</p>
            </div>
            <div className="flex justify-center mb-3 bg-slate-100 rounded-lg p-2">
              <canvas ref={cameraCanvasRef} />
            </div>
            <div className="flex items-center gap-1.5">
              <p className={`flex-1 text-[10px] font-mono truncate rounded px-2 py-1 ${urlBg} ${urlColor}`}>
                {cameraUrlWithPwd || cameraUrl}
              </p>
              <button
                onClick={() => handleCopy(cameraUrlWithPwd || cameraUrl, setCameraUrlCopied)}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-blue-600 hover:bg-blue-500 text-white whitespace-nowrap"
              >
                {cameraUrlCopied ? <Check size={12} /> : <Copy size={12} />}
                {cameraUrlCopied ? 'コピー済' : t('lan_session.password_copy')}
              </button>
            </div>
            <p className={`text-[10px] text-center mt-2 ${noteColor}`}>
              iPhoneでQRを読み取るとパスワード不要で参加できます
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
