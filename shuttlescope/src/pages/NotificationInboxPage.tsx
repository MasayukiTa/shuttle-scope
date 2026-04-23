import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { publicInquiryList, publicInquiryUpdate, type PublicInquiryRow } from '@/api/client'
import { useAuth } from '@/hooks/useAuth'
import { useIsLightMode } from '@/hooks/useIsLightMode'

const STATUS_LABELS: Record<PublicInquiryRow['status'], string> = {
  new: '新着',
  reviewed: '確認中',
  resolved: '対応済み',
}

export function NotificationInboxPage() {
  const { t } = useTranslation()

  const { role } = useAuth()
  const isLight = useIsLightMode()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draftNote, setDraftNote] = useState('')

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const border = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMain = isLight ? 'text-gray-900' : 'text-gray-100'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowHover = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/50'
  const inputCls = `w-full border ${isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-700'} rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${textMain}`

  const inquiriesQuery = useQuery({
    queryKey: ['public-inquiries'],
    queryFn: publicInquiryList,
    enabled: role === 'admin',
  })

  const selected = useMemo(
    () => (inquiriesQuery.data?.data ?? []).find((item) => item.id === selectedId) ?? null,
    [inquiriesQuery.data, selectedId]
  )

  const updateMutation = useMutation({
    mutationFn: ({ inquiryId, status, admin_note }: { inquiryId: number; status: PublicInquiryRow['status']; admin_note?: string | null }) =>
      publicInquiryUpdate(inquiryId, { status, admin_note }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['public-inquiries'] }),
        queryClient.invalidateQueries({ queryKey: ['public-inquiries-unread-count'] }),
      ])
    },
  })

  if (role !== 'admin') {
    return <div className="p-8 text-center text-gray-500">{t('auto.NotificationInboxPage.k1')}</div>
  }

  const items = inquiriesQuery.data?.data ?? []

  return (
    <div className="flex h-full">
      <div className={`w-[360px] shrink-0 border-r ${border} ${panelBg} overflow-y-auto`}>
        <div className={`px-5 py-4 border-b ${border}`}>
          <h1 className={`text-base font-semibold ${textMain}`}>{t('auto.NotificationInboxPage.k2')}</h1>
          <p className={`text-sm mt-1 ${textMuted}`}>{t('auto.NotificationInboxPage.k3')}</p>
        </div>
        <div className="divide-y divide-transparent">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                setSelectedId(item.id)
                setDraftNote(item.admin_note ?? '')
              }}
              className={`w-full text-left px-5 py-4 border-b ${border} ${rowHover} ${
                selectedId === item.id ? (isLight ? 'bg-blue-50' : 'bg-blue-900/20') : ''
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className={`text-sm font-semibold ${textMain}`}>{item.name}</div>
                <span
                  className={`text-[11px] px-2 py-0.5 rounded-full ${
                    item.status === 'new'
                      ? 'bg-red-100 text-red-700'
                      : item.status === 'reviewed'
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-green-100 text-green-700'
                  }`}
                >
                  {STATUS_LABELS[item.status]}
                </span>
              </div>
              <div className={`text-xs mt-1 ${textMuted}`}>{item.organization || '所属未記入'}</div>
              <div className={`text-xs mt-2 line-clamp-2 ${textMuted}`}>{item.message}</div>
            </button>
          ))}
          {items.length === 0 && <div className={`px-5 py-6 text-sm ${textMuted}`}>{t('auto.NotificationInboxPage.k4')}</div>}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {selected ? (
          <div className="max-w-4xl p-6 space-y-6">
            <div className={`rounded-xl border ${border} ${panelBg} p-6`}>
              <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                  <h2 className={`text-xl font-semibold ${textMain}`}>{selected.name}</h2>
                  <p className={`text-sm ${textMuted}`}>{new Date(selected.created_at).toLocaleString('ja-JP')}</p>
                </div>
                <div className="flex gap-2">
                  {(['new', 'reviewed', 'resolved'] as PublicInquiryRow['status'][]).map((status) => (
                    <button
                      key={status}
                      type="button"
                      onClick={() => updateMutation.mutate({ inquiryId: selected.id, status, admin_note: draftNote })}
                      className={`px-3 py-2 rounded-lg text-sm font-medium border ${
                        selected.status === status
                          ? 'bg-blue-600 text-white border-blue-600'
                          : isLight
                            ? 'bg-white text-gray-700 border-gray-300'
                            : 'bg-gray-700 text-gray-200 border-gray-600'
                      }`}
                    >
                      {STATUS_LABELS[status]}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2 mb-5">
                <div>
                  <div className={`text-xs uppercase tracking-wide ${textMuted}`}>{t('auto.NotificationInboxPage.k5')}</div>
                  <div className={`text-sm mt-1 ${textMain}`}>{selected.organization || '未記入'}</div>
                </div>
                <div>
                  <div className={`text-xs uppercase tracking-wide ${textMuted}`}>{t('auto.NotificationInboxPage.k6')}</div>
                  <div className={`text-sm mt-1 ${textMain}`}>{selected.role || '未記入'}</div>
                </div>
                <div className="md:col-span-2">
                  <div className={`text-xs uppercase tracking-wide ${textMuted}`}>{t('auto.NotificationInboxPage.k7')}</div>
                  <div className={`text-sm mt-1 ${textMain}`}>{selected.contact_reference || '未記入'}</div>
                </div>
              </div>

              <div className="mb-5">
                <div className={`text-xs uppercase tracking-wide ${textMuted}`}>{t('auto.NotificationInboxPage.k8')}</div>
                <div className={`mt-2 whitespace-pre-wrap text-sm leading-7 ${textMain}`}>{selected.message}</div>
              </div>

              <div>
                <label className={`block text-sm font-medium mb-2 ${textMain}`}>{t('auto.NotificationInboxPage.k9')}</label>
                <textarea
                  value={draftNote}
                  onChange={(e) => setDraftNote(e.target.value)}
                  className={`${inputCls} min-h-[140px]`}
                  placeholder={t('auto.NotificationInboxPage.k11')}
                />
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={() =>
                      updateMutation.mutate({
                        inquiryId: selected.id,
                        status: selected.status,
                        admin_note: draftNote,
                      })
                    }
                    className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium"
                  >
                    メモを保存
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className={`h-full flex items-center justify-center text-sm ${textMuted}`}>{t('auto.NotificationInboxPage.k10')}</div>
        )}
      </div>
    </div>
  )
}
