import { useTranslation } from 'react-i18next'

/**
 * 取得 API の失敗を「データなし / 0 件 / 動画なし」と区別して示す共通の通知。
 * 失敗を空状態へ変換すると障害が統計的な少標本・未登録に見えてしまうため、
 * query の isError のときはこれを出す。
 */
export function QueryErrorNotice({
  onRetry,
  className = '',
}: {
  onRetry?: () => void
  className?: string
}) {
  const { t } = useTranslation()
  return (
    <div role="alert" className={`text-sm text-center py-4 text-red-400 ${className}`}>
      <p>{t('common_ui.query_failed')}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 px-3 py-1 rounded-ss-md border border-[var(--ss-border)] text-xs text-[var(--ss-t2)] hover:bg-[var(--ss-surface-2)]"
        >
          {t('common_ui.query_retry')}
        </button>
      )}
    </div>
  )
}
