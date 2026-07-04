/**
 * BenchModeToggle — ベンチサイドでのモバイル可読性向上 toggle。
 * 状態は localStorage('bench_mode_active') に保持。
 * 親側で useBenchMode() を読んでレイアウトを切替える。
 */
import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'

const KEY = 'bench_mode_active'

export function useBenchMode(): [boolean, (v: boolean) => void] {
  const [active, setActive] = useState<boolean>(() => {
    try {
      return localStorage.getItem(KEY) === '1'
    } catch {
      return false
    }
  })
  const set = useCallback((v: boolean) => {
    setActive(v)
    try {
      localStorage.setItem(KEY, v ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [])
  // 他タブ同期
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) setActive(e.newValue === '1')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  return [active, set]
}

interface Props {
  active: boolean
  onToggle: (v: boolean) => void
}

export function BenchModeToggle({ active, onToggle }: Props) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      data-tutorial="dashboard.bench_mode"
      onClick={() => onToggle(!active)}
      aria-pressed={active}
      className={
        active
          ? 'inline-flex items-center gap-2 px-3 py-1.5 rounded-ss-pill bg-[var(--ss-brand)] text-white text-sm font-semibold border border-[var(--ss-brand-hover)] transition-colors duration-fast ease-out'
          : 'inline-flex items-center gap-2 px-3 py-1.5 rounded-ss-pill bg-[var(--ss-surface-2)] text-[var(--ss-t1)] text-sm font-medium border border-[var(--ss-border-strong)] hover:bg-[var(--ss-surface-3)] transition-colors duration-fast ease-out'
      }
    >
      <span aria-hidden="true">{active ? '●' : '○'}</span>
      {active
        ? t('auto.BenchMode.on_label')
        : t('auto.BenchMode.off_label')}
    </button>
  )
}
