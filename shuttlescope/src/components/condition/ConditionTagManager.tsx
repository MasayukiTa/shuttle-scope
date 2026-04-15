import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RoleGuard } from '@/components/common/RoleGuard'
import {
  useConditionTags,
  useCreateConditionTag,
  useDeleteConditionTag,
  type ConditionTag,
} from '@/hooks/useConditionTags'

// coach/analyst 限定: 選手ごとの期間タグ CRUD UI。
// 一覧 + 追加フォーム + 削除ボタン。編集はシンプルさ優先で削除→再作成で対応。
interface Props {
  playerId: number
  isLight?: boolean
}

const DEFAULT_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#a855f7']

export function ConditionTagManager({ playerId, isLight }: Props) {
  const { t } = useTranslation()
  const { data: tags = [], isLoading } = useConditionTags(playerId)
  const create = useCreateConditionTag()
  const del = useDeleteConditionTag(playerId)

  const [label, setLabel] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [color, setColor] = useState<string>('#3b82f6')
  const [error, setError] = useState<string | null>(null)

  const inputCls = isLight
    ? 'border border-gray-300 bg-white text-gray-900 rounded px-2 py-1.5'
    : 'border border-gray-600 bg-gray-800 text-white rounded px-2 py-1.5'
  const labelCls = isLight ? 'text-xs text-gray-600' : 'text-xs text-gray-400'
  const cardCls = isLight
    ? 'border border-gray-200 bg-white rounded p-3'
    : 'border border-gray-700 bg-gray-900 rounded p-3'

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!label.trim() || !startDate) {
      setError(t('condition.tags.error_required'))
      return
    }
    if (endDate && endDate < startDate) {
      setError(t('condition.tags.error_end_before_start'))
      return
    }
    try {
      await create.mutateAsync({
        player_id: playerId,
        label: label.trim(),
        start_date: startDate,
        end_date: endDate || null,
        color,
      })
      setLabel('')
      setStartDate('')
      setEndDate('')
      setColor('#3b82f6')
    } catch (err) {
      setError((err as Error).message || 'failed')
    }
  }

  return (
    <RoleGuard allowedRoles={['analyst', 'coach']}>
      <div className="space-y-4">
        <div>
          <h3 className={isLight ? 'text-sm font-semibold text-gray-800' : 'text-sm font-semibold text-gray-100'}>
            {t('condition.tags.title')}
          </h3>
          <p className={labelCls}>{t('condition.tags.description')}</p>
        </div>

        {/* 追加フォーム */}
        <form onSubmit={onSubmit} className={cardCls + ' space-y-3'}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className={labelCls}>{t('condition.tags.label')}</span>
              <input
                type="text"
                className={inputCls}
                value={label}
                maxLength={100}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('condition.tags.label_placeholder')}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelCls}>{t('condition.tags.color')}</span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  className="w-10 h-9 rounded border border-gray-400 bg-transparent"
                  value={color}
                  onChange={(e) => setColor(e.target.value)}
                />
                <div className="flex gap-1">
                  {DEFAULT_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      aria-label={c}
                      onClick={() => setColor(c)}
                      className="w-6 h-6 rounded border border-gray-400"
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </div>
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelCls}>{t('condition.tags.start_date')}</span>
              <input
                type="date"
                className={inputCls}
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className={labelCls}>
                {t('condition.tags.end_date')} <span className="opacity-60">({t('condition.tags.optional')})</span>
              </span>
              <input
                type="date"
                className={inputCls}
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </label>
          </div>
          {error && <div className="text-xs text-red-500">{error}</div>}
          <div>
            <button
              type="submit"
              disabled={create.isPending}
              className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm disabled:opacity-50"
            >
              {t('condition.tags.add')}
            </button>
          </div>
        </form>

        {/* 一覧 */}
        <div className={cardCls}>
          {isLoading && <div className={labelCls}>...</div>}
          {!isLoading && tags.length === 0 && (
            <div className={labelCls}>{t('condition.tags.empty')}</div>
          )}
          {!isLoading && tags.length > 0 && (
            <ul className="divide-y divide-gray-200 dark:divide-gray-700">
              {tags.map((tag: ConditionTag) => (
                <li key={tag.id} className="flex items-center gap-3 py-2">
                  <span
                    className="inline-block w-3 h-3 rounded"
                    style={{ backgroundColor: tag.color }}
                    aria-hidden
                  />
                  <span className={isLight ? 'text-sm text-gray-900 flex-1' : 'text-sm text-gray-100 flex-1'}>
                    <span className="font-medium">{tag.label}</span>
                    <span className={labelCls + ' ml-2'}>
                      {tag.start_date}
                      {tag.end_date ? ` - ${tag.end_date}` : ` (${t('condition.tags.single_day')})`}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm(t('condition.tags.confirm_delete', { label: tag.label }))) {
                        del.mutate(tag.id)
                      }
                    }}
                    className="text-xs text-red-500 hover:text-red-400"
                  >
                    {t('condition.tags.delete')}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </RoleGuard>
  )
}
