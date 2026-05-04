/**
 * U3 設定モード — JMP 風 Dropdown 階層化 (U8 で完成形へ)。
 *
 * 現状 (U3): 主要トグル + キーボードショートカット + flipMode + コートキャリブ
 * U8 で「カテゴリ ▼ → サブ ▼ → ラベル」の Dropdown 階層化を実装。
 */
import { ReactNode, useState } from 'react'
import { MIcon } from '@/components/common/MIcon'
import { useAnnotationStore } from '@/store/annotationStore'

interface Section {
  key: string
  title: string
  icon: string
  body: ReactNode
}

interface SettingsModePanelProps {
  isMatchDayMode: boolean
  onToggleMatchDayMode: () => void
  isBasicMode: boolean
  onToggleAnnotationMode: () => void
  onOpenCalibration?: () => void
  onOpenKeyboardLegend?: () => void
}

export function SettingsModePanel({
  isMatchDayMode,
  onToggleMatchDayMode,
  isBasicMode,
  onToggleAnnotationMode,
  onOpenCalibration,
  onOpenKeyboardLegend,
}: SettingsModePanelProps) {
  const flipMode = useAnnotationStore((s) => s.flipMode)
  const setFlipMode = useAnnotationStore((s) => s.setFlipMode)
  const [openKey, setOpenKey] = useState<string | null>('mode')

  const sections: Section[] = [
    {
      key: 'mode',
      title: '記録モード',
      icon: 'tune',
      body: (
        <div className="space-y-2">
          <Row
            label="試合中モード"
            sub="ボタン大型・キーボードヒント抑制"
            on={isMatchDayMode}
            onClick={onToggleMatchDayMode}
          />
          <Row
            label="アノテーション方式"
            sub={isBasicMode ? '手動記録' : '補助記録 (CV候補参照)'}
            on={!isBasicMode}
            onClick={onToggleAnnotationMode}
          />
        </div>
      ),
    },
    {
      key: 'flip',
      title: '打者 flip 動作',
      icon: 'swap_horiz',
      body: (
        <div className="space-y-1.5">
          {(['auto', 'semi-auto', 'manual'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setFlipMode(m)}
              className={
                'w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-xs transition-colors ' +
                (flipMode === m
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-200 hover:bg-gray-600')
              }
            >
              <span>{labelForFlip(m)}</span>
              <span className="text-[10px] opacity-70">{m}</span>
            </button>
          ))}
          <p className="text-[10px] text-gray-500 mt-1">
            semi-auto = flip するが 500ms 以内の次ショットで revert (バウンス対策)
          </p>
        </div>
      ),
    },
    {
      key: 'court',
      title: 'コートキャリブレーション',
      icon: 'crop_square',
      body: (
        <button
          onClick={onOpenCalibration}
          disabled={!onOpenCalibration}
          className="w-full px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          キャリブレーション画面を開く
        </button>
      ),
    },
    {
      key: 'keys',
      title: 'キーボード',
      icon: 'keyboard',
      body: (
        <button
          onClick={onOpenKeyboardLegend}
          disabled={!onOpenKeyboardLegend}
          className="w-full px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ショートカット凡例を表示
        </button>
      ),
    },
  ]

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <header className="flex items-center gap-2 px-3 py-2 text-sm font-medium border-b border-gray-700 shrink-0 bg-gray-800/40 text-gray-200">
        <MIcon name="settings" size={18} />
        設定モード
      </header>
      <div className="px-3 py-3 space-y-2 text-xs">
        {sections.map((sec) => {
          const open = openKey === sec.key
          return (
            <div key={sec.key} className="border border-gray-700 rounded">
              <button
                type="button"
                onClick={() => setOpenKey(open ? null : sec.key)}
                aria-expanded={open}
                className="w-full flex items-center justify-between gap-2 px-2 py-1.5 text-gray-200 hover:bg-gray-800/50"
              >
                <span className="flex items-center gap-2">
                  <MIcon name={sec.icon} size={16} />
                  {sec.title}
                </span>
                <MIcon name={open ? 'expand_less' : 'expand_more'} size={16} />
              </button>
              {open && <div className="px-2 py-2 border-t border-gray-700">{sec.body}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Row({
  label, sub, on, onClick,
}: { label: string; sub?: string; on: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-left text-gray-200"
    >
      <span className="flex flex-col">
        <span>{label}</span>
        {sub && <span className="text-[10px] text-gray-400">{sub}</span>}
      </span>
      <span
        className={
          'text-[10px] px-1.5 py-0.5 rounded font-mono ' +
          (on ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400')
        }
      >
        {on ? 'ON' : 'OFF'}
      </span>
    </button>
  )
}

function labelForFlip(m: 'auto' | 'semi-auto' | 'manual'): string {
  if (m === 'auto') return '完全自動 flip'
  if (m === 'semi-auto') return '準自動 flip (推奨)'
  return '手動 (常に打者 tap)'
}
