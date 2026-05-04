/**
 * データ不足時の案内メッセージ。
 * 「データ不足」と表示する代わりに「あとN件で表示できます」を表示する。
 */
import { useTranslation } from 'react-i18next'

interface NoDataMessageProps {
  sampleSize: number
  minRequired?: number
  unit?: string
}

export function NoDataMessage({ sampleSize, minRequired = 1, unit }: NoDataMessageProps) {
  const { t } = useTranslation()
  const u = unit ?? t('no_data_message.unit_default')
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
