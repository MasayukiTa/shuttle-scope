/**
 * データ不足時の案内メッセージ。
 *
 * 重要 (2026-05-19): 「データ不足」と断言することは「本来あるはずのデータが
 * ない」という強い主張に等しい。誤って表示されたユーザは「アプリが嘘をついた」
 * と認識する。そのため、loading フラグ (= useQuery の isPending / isFetching /
 * 未解決 disabled) が真の間は決して "不足" と表示せず、明示的な「計算中…」を
 * 出す。呼び出し側は必ず loading を渡すこと。
 */
import { useTranslation } from 'react-i18next'

interface NoDataMessageProps {
  sampleSize: number
  minRequired?: number
  unit?: string
  /**
   * クエリが pending/fetching/idle(disabled) なら true。
   * 真なら「データ不足」と判断せず「計算中…」を表示する (誤判定で
   * ユーザに虚偽情報を見せないため)。
   */
  loading?: boolean
}

export function NoDataMessage({ sampleSize, minRequired = 1, unit, loading }: NoDataMessageProps) {
  const { t } = useTranslation()
  const u = unit ?? t('no_data_message.unit_default')
  // ── 安全側に倒す: loading 中は「データ不足」を絶対に表示しない ─────
  if (loading) {
    return (
      <div className="py-4 text-center">
        <div className="inline-flex items-center gap-2 text-sm text-gray-500">
          <span className="inline-block w-3 h-3 rounded-full bg-blue-400 animate-pulse" />
          <span>{t('no_data_message.loading') || 'データを取得しています…'}</span>
        </div>
      </div>
    )
  }
  const needed = Math.max(0, minRequired - sampleSize)
  return (
    <div className="py-4 text-center">
      <p className="text-sm text-gray-500">
        {t('no_data_message.prefix')}<span className="font-semibold text-gray-400 mx-0.5">{needed}</span>{u}{t('no_data_message.suffix')}
      </p>
      {sampleSize > 0 && (
        <p className="text-xs text-gray-600 mt-0.5">{t('no_data_message.current')} {sampleSize}{u}</p>
      )}
    </div>
  )
}
