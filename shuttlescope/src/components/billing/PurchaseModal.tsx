import { useState } from 'react'
import { createOrder, PAYMENT_METHODS, BILLING_UI_ENABLED } from '@/api/billing'

/**
 * 商品購入モーダル (Phase Pay-1、フロント非公開)。
 *
 * 表示制御:
 *   VITE_SS_BILLING_UI_ENABLED=true のときのみマウント
 *   (= デフォルト false なら何も描画されない)
 *
 * 使い方 (Phase Pay-2 切替時):
 * ```tsx
 * <PurchaseModal
 *   productCode="report_full"
 *   productLabel="フル解析レポート (PDF)"
 *   priceJpy={500}
 *   extraMetadata={{ match_id: 123 }}
 *   onClose={() => setShow(false)}
 * />
 * ```
 */
interface Props {
  productCode: string
  productLabel: string
  priceJpy: number
  extraMetadata?: Record<string, unknown>
  onClose: () => void
}

export function PurchaseModal({ productCode, productLabel, priceJpy, extraMetadata, onClose }: Props) {
  if (!BILLING_UI_ENABLED) return null

  const [paymentMethod, setPaymentMethod] = useState<string>('credit_card')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleProceed = async () => {
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      const order = await createOrder(productCode, paymentMethod, extraMetadata)
      // プロバイダ Hosted Checkout へ遷移
      window.location.href = order.redirect_url
    } catch (err: any) {
      setError(err?.message ?? String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
        <h2 className="text-lg font-bold">{productLabel}</h2>
        <div className="text-2xl font-bold">¥{priceJpy.toLocaleString()}</div>

        <div>
          <label className="block text-sm font-medium mb-2">お支払い方法</label>
          <div className="grid grid-cols-2 gap-2">
            {PAYMENT_METHODS.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => setPaymentMethod(m.key)}
                className={`text-xs px-3 py-2 rounded border text-left transition-colors ${
                  paymentMethod === m.key
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 font-medium'
                    : 'border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-2">
            {error}
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-2 pt-2">
          <button
            onClick={handleProceed}
            disabled={loading}
            className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded disabled:opacity-50"
          >
            {loading ? '処理中...' : '決済へ進む'}
          </button>
          <button
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm rounded hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            キャンセル
          </button>
        </div>

        <p className="text-[10px] text-gray-500 text-center">
          決済画面は外部の決済代行サービス (Stripe / KOMOJU) に遷移します。
          カード情報は弊社サーバを通過しません。
        </p>
      </div>
    </div>
  )
}
