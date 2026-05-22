import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { apiGet } from '@/api/client'
import { BILLING_UI_ENABLED, OrderSummary, receiptDownloadUrl } from '@/api/billing'
import { useTranslation } from 'react-i18next'

/**
 * 注文履歴ページ (Phase Pay-1、フロント非公開)。
 * VITE_SS_BILLING_UI_ENABLED=false のときは / にリダイレクト。
 */
export default function AccountOrdersPage() {
  const { t } = useTranslation()

  // フラグ判定は hook を持たない外側で行う (rules-of-hooks 準拠)
  if (!BILLING_UI_ENABLED) return <Navigate to="/" replace />
  return <AccountOrdersPageInner />
}

function AccountOrdersPageInner() {
  const { t } = useTranslation()

  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // 自分の注文一覧 API はまだ提供していないので、admin_orders は使えない。
    // Phase Pay-2 で /api/_internal/billing/orders (自分の一覧) を追加する想定。
    // 現状は entitlements ベースで購入履歴の代替を表示。
    apiGet<{ success: boolean; data: any[] }>('/_internal/billing/entitlements')
      .then((r) => {
        // entitlements を OrderSummary 風にアダプト (簡易表示)
        const adapted: OrderSummary[] = (r.data || []).map((e: any) => ({
          public_id: `ent-${e.entitlement_type}`,
          amount_jpy: 0,
          currency: 'JPY',
          status: 'paid',
          payment_method: null,
          provider: null,
          created_at: e.valid_from,
          paid_at: e.valid_from,
        }))
        setOrders(adapted)
      })
      .catch((err) => setError(err?.message ?? String(err)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold mb-2">{t('auto.AccountOrdersPage.k1')}</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
        {t('auto.AccountOrdersPage.k3')}
      </p>

      {loading && <div className="text-sm">{t('auto.AccountOrdersPage.k2')}</div>}
      {error && <div className="text-sm text-red-600">{error}</div>}
      {!loading && orders.length === 0 && (
        <div className="rounded border border-gray-200 dark:border-gray-700 p-6 text-center text-sm text-gray-500">
          {t('auto.AccountOrdersPage.k4')}
        </div>
      )}

      <div className="space-y-2">
        {orders.map((o) => (
          <div key={o.public_id}
               className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div className="text-sm">
              <div className="font-medium">{t('auto.AccountOrdersPage.k5', { id: o.public_id.slice(0, 16) })}</div>
              <div className="text-xs text-gray-500">
                {t('auto.AccountOrdersPage.k6', { date: o.created_at, status: o.status })}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-sm font-medium">{t('auto.AccountOrdersPage.k7', { amount: o.amount_jpy.toLocaleString() })}</div>
              {o.status === 'paid' && (
                <a
                  href={receiptDownloadUrl(o.public_id)}
                  className="text-xs px-3 py-1 rounded border border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/20"
                >
                  {t('auto.AccountOrdersPage.k8')}
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
