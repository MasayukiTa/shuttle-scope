import { useTranslation } from 'react-i18next'

// PHASE 3（TASK-030〜034）で完全実装
export function DashboardPage() {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col h-full bg-gray-900 text-white p-6">
      <h1 className="text-xl font-semibold mb-4">{t('nav.dashboard')}</h1>
      <div className="flex-1 flex items-center justify-center text-gray-500">
        解析ダッシュボード（PHASE 3で実装）
      </div>
    </div>
  )
}
