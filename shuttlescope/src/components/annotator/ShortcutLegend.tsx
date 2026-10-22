/**
 * ShortcutLegend — キーボードショートカット一覧の単一定義。
 *
 * 旧コード: AnnotatorPage.tsx:3127-3139 (サイドバーガイド) と
 * :3338-3346 (Match Day Mode 用 legend overlay) で同じキー一覧を別々に
 * 並べていたため drift が発生 (overlay には Numpad 章があったがサイドバーにはない等)。
 *
 * 集約方針:
 * - キー定義 (`SHORTCUTS`) を 1 箇所で管理
 * - description は i18n キー参照
 * - 使う側が `compact` (サイドバー) / `expanded` (overlay) を切り替え
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'

interface Shortcut {
  keys: string
  /** i18n キー (`annotator.ui.*`) */
  i18nKey: string
  /** 表示するセクション */
  section: 'video' | 'rally' | 'shot' | 'land' | 'meta'
  /** モバイル / コンパクト時に隠すキー (上級者向けのものはここで間引き) */
  hiddenInCompact?: boolean
  /** コンパクト表示の初期状態で見せる主要キー (初見の利用者向けに数を絞る) */
  essential?: boolean
}

const SHORTCUTS: Shortcut[] = [
  // 動画コントロール
  { keys: 'Space',      i18nKey: 'annotator.ui.sc_play_pause', section: 'video', essential: true },
  { keys: '←/→',        i18nKey: 'annotator.ui.sc_frame',      section: 'video' },
  { keys: 'Shift+←/→',  i18nKey: 'annotator.ui.sc_ten_sec',    section: 'video' },
  // ラリー
  { keys: 'Enter',      i18nKey: 'annotator.ui.sc_rally_toggle', section: 'rally', essential: true },
  { keys: 'K',          i18nKey: 'annotator.ui.sc_missed',       section: 'rally' },
  { keys: 'Tab',        i18nKey: 'annotator.ui.sc_player_toggle', section: 'rally' },
  // ショット
  { keys: 'N/C/P…G',    i18nKey: 'annotator.ui.sc_shot_input', section: 'shot', essential: true },
  { keys: 'Q/W/E',      i18nKey: 'annotator.ui.sc_attr',       section: 'shot' },
  { keys: '7/8/9/0',    i18nKey: 'annotator.ui.sc_hitter',     section: 'shot', hiddenInCompact: true },
  // 落点 / 打点
  { keys: 'NumPad 1-9', i18nKey: 'annotator.ui.sc_land_zone',     section: 'land' },
  { keys: '1-9 (top)',  i18nKey: 'annotator.ui.sc_hit_zone',      section: 'land' },
  { keys: 'Shift+1-9',  i18nKey: 'annotator.ui.sc_hit_zone_doubles', section: 'land', hiddenInCompact: true },
  { keys: 'Backspace',  i18nKey: 'annotator.ui.sc_land_cancel',   section: 'land' },
  // メタ
  { keys: 'Ctrl+Z',     i18nKey: 'annotator.ui.sc_undo',       section: 'meta', essential: true },
  { keys: 'Esc',        i18nKey: 'annotator.ui.sc_cancel',     section: 'meta' },
  { keys: '1-6',        i18nKey: 'annotator.ui.sc_end_type',   section: 'meta' },
  { keys: 'A/B',        i18nKey: 'annotator.ui.sc_winner',     section: 'meta' },
  { keys: 'Ctrl+K',     i18nKey: 'annotator.ui.sc_command_palette', section: 'meta', essential: true },
]

interface ShortcutLegendProps {
  /** compact: サイドバー用 (上級キー隠し) / full: overlay 用 */
  variant?: 'compact' | 'full'
  className?: string
}

export function ShortcutLegend({ variant = 'compact', className }: ShortcutLegendProps) {
  const { t } = useTranslation()
  // コンパクト表示は主要キーだけで始め、必要なときに全部を開く。
  // 全キーは「?」キーの一覧 (full) からもいつでも見られる。
  const [showAll, setShowAll] = useState(false)
  const items = variant === 'compact'
    ? SHORTCUTS.filter((s) => (showAll ? !s.hiddenInCompact : s.essential))
    : SHORTCUTS

  return (
    <div className={clsx('bg-[var(--ss-surface-2)] rounded-ss-md p-3 text-[var(--ss-t2)]', className)}>
      <div className="font-semibold text-[var(--ss-t1)] mb-2 text-sm">
        {t('annotator.ui.shortcuts_title')}
      </div>
      <div className={clsx('grid gap-x-4 gap-y-1 text-xs', variant === 'full' ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-2')}>
        {items.map((s) => (
          <span key={s.keys + s.i18nKey} className="flex items-baseline gap-1.5">
            <kbd className="bg-[var(--ss-surface-3)] text-[var(--ss-t1)] border border-[var(--ss-border-strong)] px-1.5 py-0.5 rounded-ss-sm text-xs font-mono shrink-0 num-cell ss-num">
              {s.keys}
            </kbd>
            <span className="truncate">{t(s.i18nKey, { defaultValue: s.keys })}</span>
          </span>
        ))}
      </div>
      {variant === 'compact' && (
        <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-[var(--ss-t3)]">
          <span>{t('annotator.ui.sc_more_hint')}</span>
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            className="shrink-0 underline hover:text-[var(--ss-t1)]"
          >
            {showAll ? t('annotator.ui.sc_show_essential') : t('annotator.ui.sc_show_all')}
          </button>
        </div>
      )}
    </div>
  )
}
