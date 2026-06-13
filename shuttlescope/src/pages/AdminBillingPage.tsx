import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router-dom'
import {
  BILLING_UI_ENABLED, AdminOrder, Product,
  adminListOrders, adminListProducts, adminCreateProduct,
} from '@/api/billing'

/**
 * admin 売上ダッシュボード (Phase Pay-1、フロント非公開)。
 * VITE_SS_BILLING_UI_ENABLED=false のときは / にリダイレクト。
 */
export default function AdminBillingPage() {
  if (!BILLING_UI_ENABLED) return <Navigate to="/" replace />
  return <AdminBillingPageInner />
}

function AdminBillingPageInner() {
  const { t } = useTranslation()
  const [orders, setOrders] = useState<AdminOrder[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showProductForm, setShowProductForm] = useState(false)

  const refetch = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [o, p] = await Promise.all([
        adminListOrders(statusFilter || undefined, 200),
        adminListProducts(),
      ])
      setOrders(o)
      setProducts(p)
    } catch (err: unknown) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { refetch() }, [refetch])

  // 売上集計
  const paidOrders = orders.filter((o) => o.status === 'paid')
  const totalRevenue = paidOrders.reduce((sum, o) => sum + o.amount_jpy, 0)
  const refundedCount = orders.filter((o) => o.status === 'refunded').length

  return (
    <div className="p-4 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold">{t('admin.billing.title')}</h1>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {t('admin.billing.subtitle')}
        </p>
      </div>

      {/* サマリ */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
          <div className="text-xs text-gray-500">{t('admin.billing.summary_revenue')}</div>
          <div className="text-2xl font-bold">¥{totalRevenue.toLocaleString()}</div>
        </div>
        <div className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
          <div className="text-xs text-gray-500">{t('admin.billing.summary_orders')}</div>
          <div className="text-2xl font-bold">{orders.length}</div>
        </div>
        <div className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
          <div className="text-xs text-gray-500">{t('admin.billing.summary_refunds')}</div>
          <div className="text-2xl font-bold">{refundedCount}</div>
        </div>
      </div>

      {/* 商品マスタ */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold">{t('admin.billing.products_heading', { count: products.length })}</h2>
          <button
            onClick={() => setShowProductForm(!showProductForm)}
            className="text-xs px-3 py-1 rounded border border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-300"
          >
            {showProductForm ? t('admin.billing.close') : t('admin.billing.add_new')}
          </button>
        </div>
        {showProductForm && <ProductCreateForm onCreated={() => { setShowProductForm(false); refetch() }} />}
        <div className="space-y-1">
          {products.map((p) => (
            <div key={p.id} className="flex items-center justify-between text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded px-3 py-2">
              <div>
                <span className="font-mono text-xs text-gray-500">{p.code}</span>
                {' '}<span className="font-medium">{p.name}</span>
                {!p.is_active && <span className="ml-2 text-xs text-gray-400">{t('admin.billing.product_inactive')}</span>}
              </div>
              <div className="font-medium">¥{p.price_jpy.toLocaleString()}</div>
            </div>
          ))}
        </div>
      </div>

      {/* 注文一覧 */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold">{t('admin.billing.orders_heading')}</h2>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 rounded px-2 py-1"
          >
            <option value="">{t('admin.billing.filter_all')}</option>
            <option value="pending">pending</option>
            <option value="authorized">authorized</option>
            <option value="paid">paid</option>
            <option value="failed">failed</option>
            <option value="canceled">canceled</option>
            <option value="refunded">refunded</option>
            <option value="expired">expired</option>
          </select>
        </div>

        {loading && <div className="text-sm">{t('admin.billing.loading')}</div>}
        {error && <div className="text-sm text-red-600">{error}</div>}

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-700">
              <tr>
                <th className="px-3 py-2 text-left">id</th>
                <th className="px-3 py-2 text-left">user_id</th>
                <th className="px-3 py-2 text-right">{t('admin.billing.col_amount')}</th>
                <th className="px-3 py-2 text-left">{t('admin.billing.col_status')}</th>
                <th className="px-3 py-2 text-left hidden sm:table-cell">{t('admin.billing.col_method')}</th>
                <th className="px-3 py-2 text-left hidden md:table-cell">{t('admin.billing.col_provider')}</th>
                <th className="px-3 py-2 text-left hidden md:table-cell">{t('admin.billing.col_created')}</th>
                <th className="px-3 py-2 text-left hidden lg:table-cell">{t('admin.billing.col_paid_at')}</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-gray-200 dark:border-gray-700">
                  <td className="px-3 py-1 text-xs">{o.id}</td>
                  <td className="px-3 py-1 text-xs">{o.user_id}</td>
                  <td className="px-3 py-1 text-right">¥{o.amount_jpy.toLocaleString()}</td>
                  <td className="px-3 py-1"><StatusBadge status={o.status} /></td>
                  <td className="px-3 py-1 text-xs hidden sm:table-cell">{o.payment_method}</td>
                  <td className="px-3 py-1 text-xs hidden md:table-cell">{o.provider}</td>
                  <td className="px-3 py-1 text-[10px] text-gray-500 hidden md:table-cell">{o.created_at}</td>
                  <td className="px-3 py-1 text-[10px] text-gray-500 hidden lg:table-cell">{o.paid_at}</td>
                </tr>
              ))}
              {orders.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-gray-500">{t('admin.billing.orders_empty')}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    paid: 'bg-green-100 text-green-800',
    pending: 'bg-yellow-100 text-yellow-800',
    failed: 'bg-red-100 text-red-800',
    refunded: 'bg-purple-100 text-purple-800',
    canceled: 'bg-gray-200 text-gray-700',
    expired: 'bg-gray-200 text-gray-700',
    authorized: 'bg-blue-100 text-blue-800',
  }
  return <span className={`text-xs px-2 py-0.5 rounded ${cls[status] || 'bg-gray-100'}`}>{status}</span>
}

function ProductCreateForm({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [price, setPrice] = useState<string>('500')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    if (submitting) return
    setSubmitting(true); setErr(null)
    try {
      await adminCreateProduct({
        code, name, description: description || undefined,
        price_jpy: Number(price), is_active: true,
      })
      onCreated()
      setCode(''); setName(''); setDescription(''); setPrice('500')
    } catch (e: unknown) {
      setErr(errorMessage(e))
    } finally { setSubmitting(false) }
  }

  return (
    <div className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3 mb-2 space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-2">
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t('admin.billing.form_code_placeholder')}
               className="text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1" />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('admin.billing.form_name_placeholder')}
               className="text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1" />
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('admin.billing.form_description_placeholder')}
               className="text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1" />
        <input type="number" value={price} onChange={(e) => setPrice(e.target.value)} placeholder={t('admin.billing.form_price_placeholder')}
               className="text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1" />
      </div>
      {err && <div className="text-xs text-red-600">{err}</div>}
      <button onClick={submit} disabled={submitting || !code || !name || !price}
              className="text-xs px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50">
        {t('admin.billing.form_submit')}
      </button>
    </div>
  )
}
