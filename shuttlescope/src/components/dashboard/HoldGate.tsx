// 昇格レビューで「保留 (hold)」になった分析を、数値ごと止める門。
// 警告帯だけで同じ数値を出し続けると、品質管理の判断が表示に効かない。
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { MIcon } from '@/components/common/MIcon'

interface HoldGateProps {
  /** true のとき children を描画せず「利用停止中」の説明に置き換える */
  suspended: boolean
  children: ReactNode
}

export function HoldGate({ suspended, children }: HoldGateProps) {
  const { t } = useTranslation()
  if (!suspended) return <>{children}</>
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-ss-md border border-[var(--ss-border)] bg-[var(--ss-surface-2)] px-3 py-3 text-xs text-[var(--ss-t2)]"
    >
      <MIcon name="pause_circle" size={14} className="mt-0.5 shrink-0 text-[var(--ss-warn)]" />
      <div className="space-y-0.5">
        <p className="font-medium">{t('advanced.hold_gate_title')}</p>
        <p className="text-[var(--ss-t3)]">{t('advanced.hold_gate_body')}</p>
      </div>
    </div>
  )
}
