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
    apiGet<{ success: boolean; data: Array<{ entitlement_type: string; valid_from: string }> }>(
      '/_internal/billing/entitlements',
    )
      .then((r) => {
        // entitlements を OrderSummary 風にアダプト (簡易表示)
        const adapted: OrderSummary[] = (r.data || []).map((e) => ({
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
      <p className="text-sm text-[var(--ss-t2)] mb-4">
        {t('auto.AccountOrdersPage.k3')}
      </p>

      {loading && <div className="text-sm">{t('auto.AccountOrdersPage.k2')}</div>}
      {error && <div className="text-sm text-[var(--ss-danger-text)]">{error}</div>}
      {!loading && orders.length === 0 && (
        <div className="rounded-ss-lg border border-[var(--ss-border)] p-6 text-center text-sm text-[var(--ss-t3)]">
          {t('auto.AccountOrdersPage.k4')}
        </div>
      )}

      <div className="space-y-2">
        {orders.map((o) => (
          <div key={o.public_id}
               className="rounded-ss-lg border border-[var(--ss-border)] bg-[var(--ss-surface-1)] p-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div className="text-sm">
              <div className="font-medium">{t('auto.AccountOrdersPage.k5', { id: o.public_id.slice(0, 16) })}</div>
              <div className="text-xs ss-num text-[var(--ss-t3)]">
                {t('auto.AccountOrdersPage.k6', { date: o.created_at, status: o.status })}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="text-sm font-medium ss-num">{t('auto.AccountOrdersPage.k7', { amount: o.amount_jpy.toLocaleString() })}</div>
              {o.status === 'paid' && (
                <a
                  href={receiptDownloadUrl(o.public_id)}
                  className="text-xs px-3 py-1 rounded-ss-md border border-[var(--ss-brand)] text-[var(--ss-brand)]"
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
