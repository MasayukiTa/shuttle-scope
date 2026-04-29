import { apiGet, apiPost, newIdempotencyKey } from './client'

/**
 * Phase Pay-1: 課金 API クライアント。
 *
 * 重要:
 *   - VITE_SS_BILLING_UI_ENABLED=true のときのみ UI から呼ばれる
 *   - フィーチャーフラグ false の間はモジュール自体が tree-shake で除去される想定
 *
 * 全エンドポイントは /api/_internal/billing/... に隔離。
 */

export const BILLING_UI_ENABLED =
  (import.meta.env.VITE_SS_BILLING_UI_ENABLED ?? 'false') === 'true'

export interface LegalInfo {
  company_name: string
  representative: string
  address: string
  phone: string
  phone_disclosure_policy: string
  email: string
  business_hours: string
  extra_fees: string
  payment_timing: string
  delivery_timing: string
  refund_policy: string
  invoice_registration_number: string
  consumption_tax_rate: number
  billing_enabled: boolean
}

export interface OrderSummary {
  public_id: string
  amount_jpy: number
  currency: string
  status: string
  payment_method: string | null
  provider: string | null
  created_at: string | null
  paid_at: string | null
}

export interface CreateOrderResp {
  success: boolean
  data: {
    public_id: string
    redirect_url: string
    amount_jpy: number
    payment_method: string
    provider: string
  }
}

export interface Entitlement {
  entitlement_type: string
  resource_type: string | null
  resource_id: number | null
  valid_from: string | null
  valid_to: string | null
}

export const PAYMENT_METHODS: Array<{ key: string; label: string; provider: string }> = [
  { key: 'credit_card',   label: 'クレジットカード',           provider: 'stripe' },
  { key: 'apple_pay',     label: 'Apple Pay',                  provider: 'stripe' },
  { key: 'google_pay',    label: 'Google Pay',                 provider: 'stripe' },
  { key: 'paypay',        label: 'PayPay',                     provider: 'komoju' },
  { key: 'merpay',        label: 'メルペイ',                   provider: 'komoju' },
  { key: 'rakuten_pay',   label: '楽天ペイ',                   provider: 'komoju' },
  { key: 'linepay',       label: 'LINE Pay',                   provider: 'komoju' },
  { key: 'konbini',       label: 'コンビニ決済',               provider: 'komoju' },
  { key: 'bank_transfer', label: '銀行振込',                   provider: 'komoju' },
  { key: 'd_barai',       label: 'd 払い (Phase Pay-3)',       provider: 'univapay' },
  { key: 'au_pay',        label: 'au PAY (Phase Pay-3)',       provider: 'univapay' },
]

export async function getLegalInfo(): Promise<LegalInfo> {
  const r = await apiGet<{ success: boolean; data: LegalInfo }>('/_internal/billing/legal_info')
  return r.data
}

export async function createOrder(productCode: string, paymentMethod: string,
                                  extraMetadata?: Record<string, unknown>): Promise<CreateOrderResp['data']> {
  const r = await apiPost<CreateOrderResp>(
    '/_internal/billing/orders',
    { product_code: productCode, payment_method: paymentMethod, extra_metadata: extraMetadata ?? null },
    { 'X-Idempotency-Key': newIdempotencyKey() },
  )
  return r.data
}

export async function getOrder(publicId: string): Promise<OrderSummary> {
  const r = await apiGet<{ success: boolean; data: OrderSummary }>(`/_internal/billing/orders/${publicId}`)
  return r.data
}

export async function cancelOrder(publicId: string): Promise<OrderSummary> {
  const r = await apiPost<{ success: boolean; data: OrderSummary }>(
    `/_internal/billing/orders/${publicId}/cancel`, {},
    { 'X-Idempotency-Key': newIdempotencyKey() },
  )
  return r.data
}

export async function listMyEntitlements(): Promise<Entitlement[]> {
  const r = await apiGet<{ success: boolean; data: Entitlement[] }>('/_internal/billing/entitlements')
  return r.data
}

export function receiptDownloadUrl(publicId: string): string {
  // ダウンロードはブラウザ直接 fetch ではなく <a href> を推奨
  // (PDF を blob で扱うには別途 fetch + URL.createObjectURL 必要)
  return `/api/_internal/billing/orders/${publicId}/receipt`
}

// admin
export interface AdminOrder extends OrderSummary {
  id: number
  user_id: number
  product_id: number
  provider_session_id: string | null
  provider_payment_id: string | null
  extra_metadata: string | null
}

export async function adminListOrders(status?: string, limit = 100): Promise<AdminOrder[]> {
  const params: Record<string, string> = { limit: String(limit) }
  if (status) params.status = status
  const r = await apiGet<{ success: boolean; data: AdminOrder[] }>('/_internal/billing/admin/orders', params)
  return r.data
}

export interface Product {
  id: number
  code: string
  name: string
  description: string | null
  price_jpy: number
  is_active: boolean
  created_at: string | null
}

export async function adminListProducts(): Promise<Product[]> {
  const r = await apiGet<{ success: boolean; data: Product[] }>('/_internal/billing/admin/products')
  return r.data
}

export async function adminCreateProduct(p: { code: string; name: string; description?: string; price_jpy: number; is_active?: boolean }) {
  return apiPost('/_internal/billing/admin/products', p,
    { 'X-Idempotency-Key': newIdempotencyKey() })
}
