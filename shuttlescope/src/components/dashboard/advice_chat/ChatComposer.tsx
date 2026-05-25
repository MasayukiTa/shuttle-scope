/**
 * ChatComposer — チャット入力欄。
 *
 * - textarea は 1〜5 行で自動拡縮。
 * - Enter で送信 / Shift+Enter 改行 / Cmd|Ctrl+Enter でも送信。
 * - 文字数カウンタ (typing 中のみ表示)。1500 で黄, 1900 で赤。
 * - 入力テキストから parsePeriod() で日付範囲を検出し、確認チップ表示。
 *   ユーザが [✕] でクリアすると、そのメッセージ中は再検出しない (dismissed flag)。
 *   [編集] で from/to の手入力 override が可能。
 */
import { forwardRef, KeyboardEvent, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { parsePeriod, ParsedPeriod } from '@/utils/parsePeriod'
import { parseShotType, parseZone } from '@/utils/parseSlots'

const MAX_LEN = 2000
const DEBOUNCE_MS = 150

export interface ComposerPeriod {
  dateFrom: string | null
  dateTo: string | null
}

export interface ComposerExtras {
  period: ComposerPeriod | null
  shotType: string | null
  zone: string | null
}

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: (extras: ComposerExtras) => void
  isSending: boolean
}

interface PeriodState {
  dateFrom: string | null
  dateTo: string | null
  label: string
  confidence: 'exact' | 'heuristic'
  // user が手動 override したか
  manual: boolean
}

export const ChatComposer = forwardRef<HTMLTextAreaElement, Props>(
  ({ value, onChange, onSend, isSending }, ref) => {
    const { t, i18n } = useTranslation()
    const lang: 'ja' | 'en' = i18n.language?.startsWith('en') ? 'en' : 'ja'

    const [debouncedValue, setDebouncedValue] = useState(value)
    const [dismissed, setDismissed] = useState(false)
    const [manualPeriod, setManualPeriod] = useState<PeriodState | null>(null)
    const [editorOpen, setEditorOpen] = useState(false)
    const [draftFrom, setDraftFrom] = useState('')
    const [draftTo, setDraftTo] = useState('')

    // debounce
    useEffect(() => {
      const h = window.setTimeout(() => setDebouncedValue(value), DEBOUNCE_MS)
      return () => window.clearTimeout(h)
    }, [value])

    // 入力が空になったら dismiss / manual 状態をリセット (次メッセージ用)
    useEffect(() => {
      if (value.length === 0) {
        setDismissed(false)
        setManualPeriod(null)
        setEditorOpen(false)
      }
    }, [value])

    const parsed: ParsedPeriod = useMemo(
      () => parsePeriod(debouncedValue, new Date(), lang),
      [debouncedValue, lang],
    )

    const parsedShot = useMemo(() => parseShotType(debouncedValue), [debouncedValue])
    const parsedZone = useMemo(() => parseZone(debouncedValue), [debouncedValue])

    const activePeriod: PeriodState | null = useMemo(() => {
      if (manualPeriod) return manualPeriod
      if (dismissed) return null
      if (parsed.confidence === 'none') return null
      return {
        dateFrom: parsed.dateFrom,
        dateTo: parsed.dateTo,
        label: parsed.label,
        confidence: parsed.confidence,
        manual: false,
      }
    }, [parsed, manualPeriod, dismissed])

    // auto-resize
    useEffect(() => {
      const ta = (ref as React.MutableRefObject<HTMLTextAreaElement | null>)?.current
      if (!ta) return
      ta.style.height = 'auto'
      const lineHeight = 20
      const maxHeight = lineHeight * 5 + 16
      ta.style.height = `${Math.min(ta.scrollHeight, maxHeight)}px`
    }, [value, ref])

    const handleSend = () => {
      const periodOut: ComposerPeriod | null =
        activePeriod && (activePeriod.dateFrom || activePeriod.dateTo)
          ? { dateFrom: activePeriod.dateFrom, dateTo: activePeriod.dateTo }
          : null
      onSend({
        period: periodOut,
        shotType: parsedShot?.code ?? null,
        zone: parsedZone?.code ?? null,
      })
      setDismissed(false)
      setManualPeriod(null)
      setEditorOpen(false)
    }

    const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Cmd/Ctrl+Enter は常に送信
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
        e.preventDefault()
        handleSend()
        return
      }
      if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault()
        handleSend()
      }
    }

    const openEditor = () => {
      setDraftFrom(activePeriod?.dateFrom ?? '')
      setDraftTo(activePeriod?.dateTo ?? '')
      setEditorOpen(true)
    }

    const applyEditor = () => {
      const ISO = /^\d{4}-\d{2}-\d{2}$/
      const f = ISO.test(draftFrom) ? draftFrom : null
      const tt = ISO.test(draftTo) ? draftTo : null
      if (!f && !tt) {
        setEditorOpen(false)
        return
      }
      setManualPeriod({
        dateFrom: f,
        dateTo: tt,
        label: `${f ?? '…'} → ${tt ?? t('auto.AdviceChat.period.today')}`,
        confidence: 'exact',
        manual: true,
      })
      setDismissed(false)
      setEditorOpen(false)
    }

    const clearPeriod = () => {
      setDismissed(true)
      setManualPeriod(null)
      setEditorOpen(false)
    }

    const n = value.length
    const showCounter = n > 0
    const counterClass =
      n >= 1900
        ? 'text-red-600 dark:text-red-400'
        : n >= 1500
        ? 'text-yellow-600 dark:text-yellow-400'
        : 'text-gray-500'
    const disabled = isSending || value.trim().length === 0

    const badgeClass =
      activePeriod?.confidence === 'exact'
        ? 'bg-green-600 text-white'
        : 'bg-yellow-500 text-white'

    return (
      <div className="flex flex-col gap-1.5">
        {activePeriod && (
          <div
            className="flex items-center flex-wrap gap-1.5 text-[11px] bg-indigo-50 dark:bg-indigo-900/40 border border-indigo-200 dark:border-indigo-700 rounded-md px-2 py-1"
            aria-label={t('auto.AdviceChat.period.chipLabel')}
          >
            <MIcon name="event" size={14} ariaHidden className="text-indigo-700 dark:text-indigo-200" />
            <span className="font-medium text-indigo-900 dark:text-indigo-100">
              {activePeriod.label}
            </span>
            <span
              className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] ${badgeClass}`}
            >
              {t('auto.AdviceChat.period.estimated')}
            </span>
            <button
              type="button"
              onClick={openEditor}
              className="inline-flex items-center gap-0.5 text-indigo-700 dark:text-indigo-200 hover:underline"
            >
              <MIcon name="edit" size={12} ariaHidden />
              {t('auto.AdviceChat.period.edit')}
            </button>
            <button
              type="button"
              onClick={clearPeriod}
              aria-label={t('auto.AdviceChat.period.clear')}
              className="inline-flex items-center text-indigo-700 dark:text-indigo-200 hover:text-red-600"
            >
              <MIcon name="close" size={14} ariaHidden />
            </button>
          </div>
        )}

        {(parsedShot || parsedZone) && (
          <div className="flex items-center flex-wrap gap-1.5 text-[11px]">
            {parsedShot && (
              <span className="inline-flex items-center gap-1 bg-emerald-50 dark:bg-emerald-900/40 border border-emerald-200 dark:border-emerald-700 text-emerald-900 dark:text-emerald-100 px-2 py-0.5 rounded-full">
                <MIcon name="sports_tennis" size={12} ariaHidden />
                <span>{parsedShot.label}</span>
              </span>
            )}
            {parsedZone && (
              <span className="inline-flex items-center gap-1 bg-amber-50 dark:bg-amber-900/40 border border-amber-200 dark:border-amber-700 text-amber-900 dark:text-amber-100 px-2 py-0.5 rounded-full">
                <MIcon name="place" size={12} ariaHidden />
                <span>{parsedZone.label}</span>
              </span>
            )}
          </div>
        )}

        {editorOpen && (
          <div className="flex items-center flex-wrap gap-2 text-[11px] bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md px-2 py-2 shadow-sm">
            <label className="flex items-center gap-1">
              <span className="text-gray-700 dark:text-gray-200">
                {t('auto.AdviceChat.period.popoverFrom')}
              </span>
              <input
                type="date"
                value={draftFrom}
                onChange={(e) => setDraftFrom(e.target.value)}
                className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 rounded px-1 py-0.5"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="text-gray-700 dark:text-gray-200">
                {t('auto.AdviceChat.period.popoverTo')}
              </span>
              <input
                type="date"
                value={draftTo}
                onChange={(e) => setDraftTo(e.target.value)}
                className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 rounded px-1 py-0.5"
              />
            </label>
            <button
              type="button"
              onClick={applyEditor}
              className="px-2 py-0.5 rounded bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              {t('auto.AdviceChat.period.popoverApply')}
            </button>
          </div>
        )}

        <div className="relative flex items-end gap-2">
          <div className="relative flex-1">
            <textarea
              ref={ref}
              value={value}
              onChange={(e) => onChange(e.target.value.slice(0, MAX_LEN))}
              onKeyDown={onKeyDown}
              rows={1}
              maxLength={MAX_LEN}
              placeholder={t('auto.AdviceChat.placeholder')}
              disabled={isSending}
              aria-label={t('auto.AdviceChat.placeholder')}
              className="w-full resize-none rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 pr-14 text-sm leading-relaxed text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60"
            />
            {showCounter && (
              <span
                className={`absolute top-1 right-2 text-[10px] tabular-nums ${counterClass}`}
                aria-live="polite"
              >
                {t('auto.AdviceChat.char_counter', { n })}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleSend}
            disabled={disabled}
            aria-label={t('auto.AdviceChat.send')}
            title={t('auto.AdviceChat.send')}
            className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <MIcon name="send" size={18} ariaHidden className="text-white" />
          </button>
        </div>
      </div>
    )
  },
)
ChatComposer.displayName = 'ChatComposer'
