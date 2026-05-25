/**
 * ChatMessageBubble — 1 メッセージのバブル表示。
 *
 * - user / ai / system を判別し、左右配置・色・尻尾形状を切替。
 * - showAvatar=true のときのみアバター描画 (連続同 author の最初だけ)。
 * - 新着 AI メッセージは typewriter で 1 文字ずつ表示する。
 */
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'
import { ChatMessage } from './useAdviceChat'
import { useTypewriter } from './useTypewriter'

interface Props {
  msg: ChatMessage
  showAvatar: boolean
  isAdmin: boolean
  /** ユーザ画面表示名 (User メッセージ avatar 初期文字用). */
  userDisplayName: string | null
  /** true ならこのメッセージは新着 → typewriter する。AI メッセージのみ尊重。 */
  typewrite: boolean
  /** typewriter 終了時に呼ぶ (newMessageIds から外す)。 */
  onTypewriterDone?: (id: ChatMessage['id']) => void
}

export function ChatMessageBubble({
  msg,
  showAvatar,
  isAdmin,
  userDisplayName,
  typewrite,
  onTypewriterDone,
}: Props) {
  const { t } = useTranslation()
  const isUser = msg.author === 'user'
  // 2026-05-25: hovered state を廃止。時刻は native title 属性経由で
  //   ブラウザの tooltip として表示する → hover で DOM 入退が起きないので
  //   バブルが上下に動く layout shift も消える。

  const conf =
    typeof msg.confidence === 'number' && isFinite(msg.confidence)
      ? Math.round(msg.confidence * 100)
      : null

  // 2026-05-25: typewriter / cursor-blink 廃止。応答は即座に全文表示する。
  // 副作用ハンドラはまだ呼び出し側が onTypewriterDone を期待しているため、
  // 新着 AI msg が初回 render された次の tick で完了通知する。
  if (!isUser && typewrite && onTypewriterDone) {
    queueMicrotask(() => onTypewriterDone(msg.id))
  }
  const isTyping = false
  const renderedContent = msg.content
  // 2026-05-25: backend は datetime.utcnow().isoformat() を返すため tz サフィックス無し。
  //   JS が naive ISO を local time と誤解して JST だと +9h ズレる。
  //   `Z` を補って UTC 確定 → toLocaleTimeString で **ブラウザの localtime** に変換。
  const tsText = (() => {
    if (!msg.created_at) return ''
    const raw = String(msg.created_at)
    const iso = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw + 'Z'
    const d = new Date(iso)
    if (isNaN(d.getTime())) return ''
    return d.toLocaleTimeString(undefined, {
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
  })()

  // ── Avatar ──
  const avatar = showAvatar ? (
    isUser ? (
      <div
        className="shrink-0 w-6 h-6 rounded-full bg-blue-200 text-blue-900 flex items-center justify-center text-[11px] font-semibold"
        aria-hidden="true"
      >
        {(userDisplayName ?? t('auto.AdviceChat.you'))[0] ?? 'U'}
      </div>
    ) : (
      <div
        className="shrink-0 w-6 h-6 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center"
        aria-hidden="true"
      >
        <MIcon name="forum" size={14} ariaHidden />
      </div>
    )
  ) : (
    <div className="shrink-0 w-6 h-6" aria-hidden="true" />
  )

  if (isUser) {
    return (
      <div className="flex items-end justify-end gap-2">
        <div className="flex flex-col items-end max-w-[75%]">
          <div
            title={tsText || undefined}
            className={`rounded-2xl rounded-tr-sm px-3 py-2 text-sm leading-relaxed bg-blue-600 text-white ${
              msg._pending ? 'opacity-70' : ''
            }`}
          >
            <div className="whitespace-pre-wrap break-words">{renderedContent}</div>
          </div>
          {(msg.date_from || msg.date_to) && (
            <div
              className="mt-1 inline-flex items-center gap-1 text-[10px] bg-indigo-100 text-indigo-900 px-1.5 py-0.5 rounded-full"
              aria-label={t('auto.AdviceChat.period.chipLabel')}
            >
              <MIcon name="event" size={11} ariaHidden />
              <span>
                {(msg.date_from ?? '…')} → {(msg.date_to ?? t('auto.AdviceChat.period.today'))}
              </span>
            </div>
          )}
          {msg.shot_type && (
            <div
              className="mt-1 inline-flex items-center gap-1 text-[10px] bg-emerald-100 text-emerald-900 px-1.5 py-0.5 rounded-full"
              aria-label={t('auto.AdviceChat.scope.slot.shotType')}
            >
              <MIcon name="sports_tennis" size={11} ariaHidden />
              <span>{msg.shot_type}</span>
            </div>
          )}
          {msg.zone && (
            <div
              className="mt-1 inline-flex items-center gap-1 text-[10px] bg-amber-100 text-amber-900 px-1.5 py-0.5 rounded-full"
              aria-label={t('auto.AdviceChat.scope.slot.zone')}
            >
              <MIcon name="place" size={11} ariaHidden />
              <span>{msg.zone}</span>
            </div>
          )}
        </div>
        {avatar}
      </div>
    )
  }

  // ── AI / system bubble ──
  return (
    <div className="flex items-end justify-start gap-2">
      {avatar}
      <div className="flex flex-col items-start max-w-[85%]">
        <div
          title={tsText || undefined}
          className="rounded-2xl rounded-tl-sm px-3 py-2 text-sm leading-relaxed bg-gray-100 text-gray-900"
        >
          <div className="whitespace-pre-wrap break-words">
            {renderedContent}
            {isTyping && null}
          </div>
        </div>
        <div className="flex items-center gap-1.5 mt-1 flex-wrap">
          {conf != null && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] bg-gray-200 text-gray-700">
              {t('auto.AdviceChat.confidence', { n: conf })}
            </span>
          )}
          {msg.is_fallback && isAdmin && (
            <span
              title={t('auto.AdviceChat.safety_hint_admin')}
              aria-label={t('auto.AdviceChat.safety_hint_admin')}
              className="inline-flex items-center text-[10px] text-amber-700"
            >
              <MIcon name="shield" size={12} ariaHidden />
            </span>
          )}
          {msg.evidence_path && (
            <a
              href={msg.evidence_path}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-blue-600 hover:underline"
            >
              {t('auto.AdviceChat.view_details')}
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
