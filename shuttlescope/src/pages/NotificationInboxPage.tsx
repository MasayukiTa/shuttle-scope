import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import {
  publicInquiryBulkDelete,
  publicInquiryDelete,
  publicInquiryList,
  publicInquiryUpdate,
  type PublicInquiryRow,
} from '@/api/client'
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

  // 折りたたみ・選択モード状態
  const [listCollapsed, setListCollapsed] = useState(false)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [dateModalOpen, setDateModalOpen] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const panelBg = isLight ? 'bg-white' : 'bg-gray-800'
  const border = isLight ? 'border-gray-200' : 'border-gray-700'
  const textMain = isLight ? 'text-gray-900' : 'text-gray-100'
  const textMuted = isLight ? 'text-gray-500' : 'text-gray-400'
  const rowHover = isLight ? 'hover:bg-gray-50' : 'hover:bg-gray-700/50'
  const inputCls = `w-full border ${isLight ? 'border-gray-300 bg-white' : 'border-gray-600 bg-gray-700'} rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${textMain}`
  const btnSecondary = `${isLight ? 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50' : 'bg-gray-700 text-gray-200 border-gray-600 hover:bg-gray-600'} border`

  const inquiriesQuery = useQuery({
    queryKey: ['public-inquiries'],
    queryFn: publicInquiryList,
    enabled: role === 'admin',
  })

  const selected = useMemo(
    () => (inquiriesQuery.data?.data ?? []).find((item) => item.id === selectedId) ?? null,
    [inquiriesQuery.data, selectedId]
  )

  const invalidateAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['public-inquiries'] }),
      queryClient.invalidateQueries({ queryKey: ['public-inquiries-unread-count'] }),
    ])
  }

  const updateMutation = useMutation({
    mutationFn: ({ inquiryId, status, admin_note }: { inquiryId: number; status: PublicInquiryRow['status']; admin_note?: string | null }) =>
      publicInquiryUpdate(inquiryId, { status, admin_note }),
    onSuccess: invalidateAll,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => publicInquiryDelete(id),
    onSuccess: async (_r, id) => {
      if (selectedId === id) setSelectedId(null)
      await invalidateAll()
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (body: Parameters<typeof publicInquiryBulkDelete>[0]) => publicInquiryBulkDelete(body),
    onSuccess: async (resp) => {
      // 削除済み ID が選択中なら選択解除
      const deletedIds = new Set(resp.data?.ids ?? [])
      if (selectedId != null && deletedIds.has(selectedId)) setSelectedId(null)
      setSelectedIds(new Set())
      setSelectionMode(false)
      await invalidateAll()
      // 件数フィードバック（通知方式はプロジェクト内の toast/alert を使用）
      // 今は最小限で alert に寄せる
      window.alert(t('auto.NotificationInboxPage.k32', { n: resp.data?.deleted ?? 0 }))
    },
  })

  if (role !== 'admin') {
    return <div className="p-8 text-center text-gray-500">{t('auto.NotificationInboxPage.k1')}</div>
  }

  const items = inquiriesQuery.data?.data ?? []

  // ── ハンドラ群 ───────────────────────────────────────────────
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDeleteOne = (id: number) => {
    if (!window.confirm(t('auto.NotificationInboxPage.k18'))) return
    deleteMutation.mutate(id)
  }

  const handleBulkDeleteSelected = () => {
    if (selectedIds.size === 0) {
      window.alert(t('auto.NotificationInboxPage.k33'))
      return
    }
    if (!window.confirm(t('auto.NotificationInboxPage.k19', { n: selectedIds.size }))) return
    bulkDeleteMutation.mutate({ ids: Array.from(selectedIds) })
  }

  const handleBulkDeleteResolved = () => {
    const resolvedCount = items.filter((x) => x.status === 'resolved').length
    if (resolvedCount === 0) {
      window.alert(t('auto.NotificationInboxPage.k33'))
      return
    }
    if (!window.confirm(t('auto.NotificationInboxPage.k23'))) return
    bulkDeleteMutation.mutate({ statuses: ['resolved'] })
  }

  const handleBulkDeleteByDate = () => {
    if (!dateFrom && !dateTo) {
      window.alert(t('auto.NotificationInboxPage.k33'))
      return
    }
    if (!window.confirm(t('auto.NotificationInboxPage.k25'))) return
    const body: Parameters<typeof publicInquiryBulkDelete>[0] = {}
    if (dateFrom) body.created_after = new Date(dateFrom).toISOString()
    if (dateTo) body.created_before = new Date(dateTo).toISOString()
    bulkDeleteMutation.mutate(body)
    setDateModalOpen(false)
    setDateFrom('')
    setDateTo('')
  }

  // ── レイアウト用フラグ ──────────────────────────────────────
  // モバイル: 詳細が選ばれていればリストを隠す / 選ばれていなければ詳細を隠す
  const showListOnMobile = selected === null
  const showDetailOnMobile = selected !== null
  // Tailwind JIT のため完全な静的クラス名で分岐する
  const listWidthCls = listCollapsed ? 'md:w-12' : 'md:w-[360px]'

  return (
    <div className="flex h-full relative">
      {/* ── リスト（左パネル） ───────────────────────────────── */}
      <div
        className={`
          ${showListOnMobile ? 'flex' : 'hidden'} md:flex
          flex-col shrink-0 border-r ${border} ${panelBg} overflow-hidden
          w-full ${listWidthCls}
          transition-[width] duration-200
        `}
      >
        {/* ヘッダー */}
        <div className={`px-4 md:px-5 py-3 md:py-4 border-b ${border} flex items-start justify-between gap-2`}>
          {!listCollapsed && (
            <div className="min-w-0 flex-1">
              <h1 className={`text-base font-semibold ${textMain} truncate`}>{t('auto.NotificationInboxPage.k2')}</h1>
              <p className={`text-xs mt-1 ${textMuted} truncate`}>{t('auto.NotificationInboxPage.k3')}</p>
            </div>
          )}
          {/* 折りたたみボタン（デスクトップのみ表示） */}
          <button
            type="button"
            onClick={() => setListCollapsed((v) => !v)}
            className={`hidden md:inline-flex items-center justify-center w-8 h-8 rounded-md ${btnSecondary} text-lg`}
            title={listCollapsed ? t('auto.NotificationInboxPage.k17') : t('auto.NotificationInboxPage.k16')}
            aria-label={listCollapsed ? t('auto.NotificationInboxPage.k17') : t('auto.NotificationInboxPage.k16')}
          >
            {listCollapsed ? '›' : '‹'}
          </button>
        </div>

        {!listCollapsed && (
          <>
            {/* 操作バー */}
            <div className={`px-3 py-2 border-b ${border} flex flex-wrap gap-1.5 text-xs`}>
              <button
                type="button"
                onClick={() => {
                  setSelectionMode((v) => !v)
                  setSelectedIds(new Set())
                }}
                className={`px-2.5 py-1.5 rounded-md ${selectionMode ? 'bg-blue-600 text-white border-blue-600 border' : btnSecondary}`}
              >
                {selectionMode
                  ? t('auto.NotificationInboxPage.k14')
                  : t('auto.NotificationInboxPage.k13')}
              </button>
              <button
                type="button"
                onClick={handleBulkDeleteResolved}
                className={`px-2.5 py-1.5 rounded-md ${btnSecondary}`}
              >
                {t('auto.NotificationInboxPage.k21')}
              </button>
              <button
                type="button"
                onClick={() => setDateModalOpen(true)}
                className={`px-2.5 py-1.5 rounded-md ${btnSecondary}`}
              >
                {t('auto.NotificationInboxPage.k22')}
              </button>
            </div>

            {/* 一覧 */}
            <div className="flex-1 overflow-y-auto">
              {items.map((item) => {
                const isChecked = selectedIds.has(item.id)
                return (
                  <div
                    key={item.id}
                    className={`flex items-stretch border-b ${border} ${
                      selectedId === item.id && !selectionMode
                        ? (isLight ? 'bg-blue-50' : 'bg-blue-900/20')
                        : ''
                    }`}
                  >
                    {selectionMode && (
                      <label className="flex items-center px-3 cursor-pointer">
                        <input
                          type="checkbox"
                          className="w-4 h-4 accent-blue-600"
                          checked={isChecked}
                          onChange={() => toggleSelect(item.id)}
                        />
                      </label>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        if (selectionMode) {
                          toggleSelect(item.id)
                          return
                        }
                        setSelectedId(item.id)
                        setDraftNote(item.admin_note ?? '')
                      }}
                      className={`flex-1 text-left px-4 md:px-5 py-3 md:py-4 ${rowHover}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className={`text-sm font-semibold ${textMain} truncate`}>{item.name}</div>
                        <span
                          className={`text-[11px] shrink-0 px-2 py-0.5 rounded-full ${
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
                      <div className={`text-xs mt-1 ${textMuted} truncate`}>{item.organization || '所属未記入'}</div>
                      <div className={`text-xs mt-2 line-clamp-2 ${textMuted}`}>{item.message}</div>
                      <div className={`text-[10px] mt-1 ${textMuted}`}>
                        {new Date(item.created_at).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}
                      </div>
                    </button>
                    {!selectionMode && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDeleteOne(item.id)
                        }}
                        className={`px-3 text-red-500 hover:bg-red-500/10`}
                        title={t('auto.NotificationInboxPage.k12')}
                        aria-label={t('auto.NotificationInboxPage.k12')}
                      >
                        🗑
                      </button>
                    )}
                  </div>
                )
              })}
              {items.length === 0 && (
                <div className={`px-5 py-6 text-sm ${textMuted}`}>
                  {t('auto.NotificationInboxPage.k4')}
                </div>
              )}
            </div>

            {/* 選択モード時のアクションバー（下部固定） */}
            {selectionMode && (
              <div className={`px-3 py-2 border-t ${border} ${panelBg} flex gap-2`}>
                <button
                  type="button"
                  onClick={handleBulkDeleteSelected}
                  disabled={bulkDeleteMutation.isPending || selectedIds.size === 0}
                  className="flex-1 px-3 py-2 rounded-md bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm font-medium"
                >
                  {t('auto.NotificationInboxPage.k20', { n: selectedIds.size })}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── 詳細（右パネル） ─────────────────────────────────── */}
      <div className={`${showDetailOnMobile ? 'flex' : 'hidden'} md:flex flex-1 flex-col overflow-y-auto`}>
        {selected ? (
          <div className="max-w-4xl w-full p-4 md:p-6 space-y-4">
            {/* モバイル用戻るボタン */}
            <button
              type="button"
              onClick={() => setSelectedId(null)}
              className={`md:hidden inline-flex items-center gap-1 text-sm ${textMuted} mb-1`}
            >
              ← {t('auto.NotificationInboxPage.k15')}
            </button>

            <div className={`rounded-xl border ${border} ${panelBg} p-4 md:p-6`}>
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div className="min-w-0">
                  <h2 className={`text-xl font-semibold ${textMain} truncate`}>{selected.name}</h2>
                  <p className={`text-sm ${textMuted}`}>{new Date(selected.created_at).toLocaleString('ja-JP')}</p>
                </div>
                <div className="flex flex-wrap gap-2">
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
                  <button
                    type="button"
                    onClick={() => handleDeleteOne(selected.id)}
                    className="px-3 py-2 rounded-lg text-sm font-medium border bg-red-600 hover:bg-red-700 text-white border-red-600"
                  >
                    {t('auto.NotificationInboxPage.k12')}
                  </button>
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
                  <div className={`text-sm mt-1 ${textMain} break-all`}>{selected.contact_reference || '未記入'}</div>
                </div>
              </div>

              <div className="mb-5">
                <div className={`text-xs uppercase tracking-wide ${textMuted}`}>{t('auto.NotificationInboxPage.k8')}</div>
                <div className={`mt-2 whitespace-pre-wrap break-words text-sm leading-7 ${textMain}`}>{selected.message}</div>
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
                    {t('auto.NotificationInboxPage.k30')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className={`h-full flex items-center justify-center text-sm ${textMuted} px-4 text-center`}>
            {t('auto.NotificationInboxPage.k10')}
          </div>
        )}
      </div>

      {/* ── 期間指定削除モーダル ─────────────────────────────── */}
      {dateModalOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setDateModalOpen(false)}
        >
          <div
            className={`${panelBg} rounded-xl border ${border} max-w-md w-full p-5 space-y-4`}
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <h3 className={`text-lg font-semibold ${textMain}`}>
                {t('auto.NotificationInboxPage.k24')}
              </h3>
              <p className={`text-sm mt-1 ${textMuted}`}>
                {t('auto.NotificationInboxPage.k25')}
              </p>
            </div>

            <div className="space-y-3">
              <div>
                <label className={`block text-xs font-medium mb-1 ${textMain}`}>
                  {t('auto.NotificationInboxPage.k26')}
                </label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={`block text-xs font-medium mb-1 ${textMain}`}>
                  {t('auto.NotificationInboxPage.k27')}
                </label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => setDateModalOpen(false)}
                className={`flex-1 px-3 py-2 rounded-md text-sm ${btnSecondary}`}
              >
                {t('auto.NotificationInboxPage.k28')}
              </button>
              <button
                type="button"
                onClick={handleBulkDeleteByDate}
                disabled={bulkDeleteMutation.isPending}
                className="flex-1 px-3 py-2 rounded-md bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm font-medium"
              >
                {t('auto.NotificationInboxPage.k29')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
