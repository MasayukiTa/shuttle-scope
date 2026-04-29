import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { BILLING_UI_ENABLED, getLegalInfo, LegalInfo } from '@/api/billing'

/**
 * 特定商取引法に基づく表記 (Phase Pay-1、フロント非公開)。
 *
 * - 全データは env (SS_LEGAL_*) から backend 経由で取得
 * - コード上に固定値はない (重要情報は env で管理)
 * - VITE_SS_BILLING_UI_ENABLED=false のときは / にリダイレクト
 *
 * Phase Pay-2 切替時には env を埋めるだけで内容が反映される。
 */
export default function CommerceLawPage() {
  if (!BILLING_UI_ENABLED) return <Navigate to="/" replace />

  const [info, setInfo] = useState<LegalInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getLegalInfo()
      .then(setInfo)
      .catch((e) => setError(e?.message ?? String(e)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-8">読み込み中...</div>
  if (error || !info) return <div className="p-8 text-red-600">{error ?? '取得失敗'}</div>

  const phoneDisplay = info.phone || info.phone_disclosure_policy

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">特定商取引法に基づく表記</h1>

      <table className="w-full text-sm border border-gray-200 dark:border-gray-700">
        <tbody>
          <Row label="販売事業者" value={info.company_name || '(未設定)'} />
          {info.representative && <Row label="運営責任者" value={info.representative} />}
          <Row label="所在地" value={info.address || '(未設定)'} />
          <Row label="電話番号" value={phoneDisplay} />
          <Row label="メールアドレス" value={info.email} />
          {info.business_hours && <Row label="営業時間" value={info.business_hours} />}
          <Row label="販売価格" value="各商品ページに記載のとおり (税込価格)" />
          {info.extra_fees && <Row label="商品代金以外の必要料金" value={info.extra_fees} />}
          <Row label="お支払方法" value="クレジットカード、Apple Pay、Google Pay、PayPay、メルペイ、楽天ペイ、LINE Pay、コンビニ決済、銀行振込" />
          <Row label="お支払時期" value={info.payment_timing} />
          <Row label="商品の引渡し時期" value={info.delivery_timing} />
          <Row label="返品・キャンセルについて" value={info.refund_policy} />
          {info.invoice_registration_number && (
            <Row label="適格請求書発行事業者登録番号" value={info.invoice_registration_number} />
          )}
        </tbody>
      </table>

      <p className="mt-6 text-xs text-gray-500">
        記載内容は予告なく変更される場合があります。最新の情報は本ページにてご確認ください。
      </p>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr className="border-b border-gray-200 dark:border-gray-700">
      <th className="text-left p-3 bg-gray-50 dark:bg-gray-800 align-top w-1/3 font-medium">{label}</th>
      <td className="p-3 whitespace-pre-wrap align-top">{value}</td>
    </tr>
  )
}
