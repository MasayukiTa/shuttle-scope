/**
 * ChatEmptyState — メッセージ 0 件時に表示する空ステート。
 * 4 つの例文 chip を 2x2 grid (mobile は stack) で並べ、タップで composer に流し込む。
 *
 * 2026-05-25 redesign: 巨大スパークル + indigo hover を廃止して slate ベース。
 */
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

const PROMPT_KEYS = [
  'prompt_recent_growth',
  'prompt_net_shots',
  'prompt_serve',
  'prompt_practice_week',
] as const

interface Props {
  onPick: (text: string) => void
}

export function ChatEmptyState({ onPick }: Props) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center py-8 px-2 gap-3 text-center">
      <MIcon
        name="forum"
        size={36}
        className="text-slate-300"
        ariaHidden
      />
      <div className="text-sm text-slate-600">
        {t('auto.AdviceChat.empty_state')}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 w-full max-w-md">
        {PROMPT_KEYS.map((k) => {
          const text = t(`auto.AdviceChat.${k}`)
          return (
            <button
              key={k}
              type="button"
              onClick={() => onPick(text)}
              className="text-xs px-3 py-2 rounded border border-slate-200 hover:border-slate-400 hover:bg-slate-50 text-slate-700 text-left"
            >
              {text}
            </button>
          )
        })}
      </div>
    </div>
  )
}
