/**
 * ChatComposer — チャット入力欄。
 *
 * - textarea は 1〜5 行で自動拡縮。
 * - Enter で送信 / Shift+Enter 改行 / Cmd|Ctrl+Enter でも送信。
 * - 文字数カウンタ (typing 中のみ表示)。1500 で黄, 1900 で赤。
 */
import { forwardRef, KeyboardEvent, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

const MAX_LEN = 2000

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  isSending: boolean
}

export const ChatComposer = forwardRef<HTMLTextAreaElement, Props>(
  ({ value, onChange, onSend, isSending }, ref) => {
    const { t } = useTranslation()

    // auto-resize
    useEffect(() => {
      const ta = (ref as React.MutableRefObject<HTMLTextAreaElement | null>)?.current
      if (!ta) return
      ta.style.height = 'auto'
      const lineHeight = 20
      const maxHeight = lineHeight * 5 + 16
      ta.style.height = `${Math.min(ta.scrollHeight, maxHeight)}px`
    }, [value, ref])

    const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Cmd/Ctrl+Enter は常に送信
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
        e.preventDefault()
        onSend()
        return
      }
      if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault()
        onSend()
      }
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

    return (
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
          onClick={onSend}
          disabled={disabled}
          aria-label={t('auto.AdviceChat.send')}
          title={t('auto.AdviceChat.send')}
          className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <MIcon name="send" size={18} ariaHidden />
        </button>
      </div>
    )
  },
)
ChatComposer.displayName = 'ChatComposer'
