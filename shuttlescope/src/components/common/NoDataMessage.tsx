/**
 * データ不足時の案内メッセージ。
 *
 * 重要 (2026-05-19 v2): 「データ不足」と断言することは「本来あるはずのデータが
 * ない」という強い主張に等しい。誤って表示されたユーザは「アプリが嘘をついた」
 * と認識する。
 *
 * 解決策: 内部に GRACE_MS の grace period を持ち、mount 直後は必ず「計算中…」を
 * 表示する。GRACE_MS 経過後に sampleSize がまだ不足なら本来のメッセージを出す。
 *
 * caller が `loading` prop を渡せばそれを優先する (loading=true なら強制計算中)。
 * 渡さなくても内部 grace period で安全に倒れるので、scope 問題で props を
 * 渡せない caller でも問題ない (= 旧 API 互換)。
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface NoDataMessageProps {
  sampleSize: number
  minRequired?: number
  unit?: string
  /**
   * クエリが pending/fetching/idle(disabled) なら true。
   * 渡されなくても内部 grace period で 1.2 秒は「計算中」表示。
   */
  loading?: boolean
}

// mount 直後の grace period (ms)。この間は「計算中」、経過後に「不足」表示。
// useQuery の典型的な初回応答時間より長め (実測 200〜600ms)。
const GRACE_MS = 1200

export function NoDataMessage({ sampleSize, minRequired = 1, unit, loading }: NoDataMessageProps) {
  const { t } = useTranslation()
  const u = unit ?? t('no_data_message.unit_default')
  const [graceElapsed, setGraceElapsed] = useState(false)

  useEffect(() => {
    const id = setTimeout(() => setGraceElapsed(true), GRACE_MS)
    return () => clearTimeout(id)
  }, [])

  // ── 安全側に倒す: loading 中 or grace period 中は「データ不足」を絶対に出さない ─
  if (loading || !graceElapsed) {
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
