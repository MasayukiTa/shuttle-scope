import { useEffect, useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { apiGet } from '@/api/client'
import { UserRole } from '@/types'

// 選手ロール選択時に player_id、コーチロール選択時に team_name を収集する共通ピッカー
// - onSelect は完了時のみ呼ばれる（キャンセル時は onCancel）
// - inline=true ならフル画面表示（初回起動用）、false なら対象ロール固定でピッカー部のみ
export type RolePickerStage =
  | { kind: 'roles' }
  | { kind: 'player' }
  | { kind: 'team' }

export function RolePicker({
  mode,
  initialStage,
  onSelect,
  onCancel,
}: {
  mode: 'initial' | 'modal'
  initialStage?: RolePickerStage
  onSelect: (role: UserRole, playerId?: number | null, teamName?: string | null) => void
  onCancel?: () => void
}) {
  const { t } = useTranslation()
  const [stage, setStage] = useState<RolePickerStage>(initialStage ?? { kind: 'roles' })
  const [players, setPlayers] = useState<Array<{ id: number; name: string; team: string | null }> | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const needsPlayers = stage.kind === 'player' || stage.kind === 'team'

  useEffect(() => {
    if (!needsPlayers) return
    let cancelled = false
    setLoadErr(null)
    apiGet<{ data: Array<{ id: number; name: string; team: string | null }> }>('/players')
      .then((res) => {
        if (cancelled) return
        setPlayers((res?.data ?? []) as Array<{ id: number; name: string; team: string | null }>)
      })
      .catch((e) => { if (!cancelled) setLoadErr(`選手一覧の取得に失敗: ${e}`) })
    return () => { cancelled = true }
  }, [needsPlayers])

  const filteredPlayers = (players ?? []).filter((p) =>
    !search.trim() || p.name.toLowerCase().includes(search.trim().toLowerCase())
  )

  const teams = useMemo(() => {
    const set = new Set<string>()
    for (const p of (players ?? [])) {
      if (p.team && p.team.trim()) set.add(p.team.trim())
    }
    return Array.from(set).filter((name) =>
      !search.trim() || name.toLowerCase().includes(search.trim().toLowerCase())
    ).sort((a, b) => a.localeCompare(b, 'ja'))
  }, [players, search])

  const wrapperCls = mode === 'initial'
    ? 'min-h-screen flex items-center justify-center bg-[var(--ss-bg-app)]'
    : 'fixed inset-0 bg-[var(--ss-bg-overlay)] flex items-center justify-center z-50 p-4'

  const panelCls = 'rounded-ss-lg p-6 w-96 max-h-[80vh] flex flex-col bg-[var(--ss-surface-1)] shadow-pop border border-[var(--ss-border)]'

  // 選択肢ボタン (選手/チーム/ロール共通): crisp control surface + hover tint。
  const optionBtnCls = 'w-full text-left px-3 py-2 rounded-ss-md text-sm transition-colors duration-fast ease-out bg-[var(--ss-surface-2)] hover:bg-[var(--ss-brand-tint)] text-[var(--ss-t1)]'

  if (stage.kind === 'player') {
    return (
      <div className={wrapperCls}>
        <div className={panelCls}>
          <div className="text-center mb-4">
            <div className="text-xl font-bold mb-1 text-[var(--ss-t1)]">{t('auto.RolePicker.k1')}</div>
            <div className="text-xs text-[var(--ss-t3)]">{t('auto.RolePicker.k2')}</div>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('auto.RolePicker.k7')}
            className="w-full mb-3 px-3 py-2 rounded-ss-md text-sm border bg-[var(--ss-ctrl-bg)] border-[var(--ss-ctrl-border)] text-[var(--ss-ctrl-text)]"
          />
          <div className="flex-1 overflow-y-auto space-y-1">
            {loadErr && <p className="text-[var(--ss-bad)] text-xs">{loadErr}</p>}
            {!loadErr && players === null && <p className="text-xs text-[var(--ss-t3)]">{t('auto.RolePicker.k3')}</p>}
            {players !== null && filteredPlayers.length === 0 && (
              <p className="text-xs text-center py-4 text-[var(--ss-t3)]">
                {players.length === 0 ? '登録選手がいません' : '該当する選手が見つかりません'}
              </p>
            )}
            {filteredPlayers.map((p) => (
              <button
                key={p.id}
                onClick={() => onSelect('player', p.id, null)}
                className={optionBtnCls}
              >
                {p.name}
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between mt-3">
            <button
              onClick={() => mode === 'initial' ? setStage({ kind: 'roles' }) : onCancel?.()}
              className="text-xs underline text-[var(--ss-t3)]"
            >
              {mode === 'initial' ? t('auto.RolePicker.back_to_roles') : t('auto.RolePicker.cancel')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (stage.kind === 'team') {
    return (
      <div className={wrapperCls}>
        <div className={panelCls}>
          <div className="text-center mb-4">
            <div className="text-xl font-bold mb-1 text-[var(--ss-t1)]">{t('auto.RolePicker.k4')}</div>
            <div className="text-xs text-[var(--ss-t3)]">{t('auto.RolePicker.k5')}</div>
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('auto.RolePicker.k8')}
            className="w-full mb-3 px-3 py-2 rounded-ss-md text-sm border bg-[var(--ss-ctrl-bg)] border-[var(--ss-ctrl-border)] text-[var(--ss-ctrl-text)]"
          />
          <div className="flex-1 overflow-y-auto space-y-1">
            {loadErr && <p className="text-[var(--ss-bad)] text-xs">{loadErr}</p>}
            {!loadErr && players === null && <p className="text-xs text-[var(--ss-t3)]">{t('auto.RolePicker.k3')}</p>}
            {players !== null && teams.length === 0 && !search.trim() && (
              <p className="text-xs text-center py-4 text-[var(--ss-t3)]">
                {t('auto.RolePicker.no_teams')}
              </p>
            )}
            {teams.map((name) => (
              <button
                key={name}
                onClick={() => onSelect('coach', null, name)}
                className={optionBtnCls}
              >
                {name}
              </button>
            ))}
            {search.trim() && !teams.includes(search.trim()) && (
              <button
                onClick={() => onSelect('coach', null, search.trim())}
                className="w-full text-left px-3 py-2 rounded-ss-md text-sm border border-dashed border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-brand-tint)] transition-colors duration-fast ease-out"
              >
                {t('auto.RolePicker.register_new_team', { name: search.trim() })}
              </button>
            )}
          </div>
          <div className="flex items-center justify-between mt-3">
            <button
              onClick={() => mode === 'initial' ? setStage({ kind: 'roles' }) : onCancel?.()}
              className="text-xs underline text-[var(--ss-t3)]"
            >
              {mode === 'initial' ? t('auto.RolePicker.back_to_roles') : t('auto.RolePicker.cancel')}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // roles ステージ
  return (
    <div className={wrapperCls}>
      <div className="rounded-ss-lg p-8 w-80 bg-[var(--ss-surface-1)] shadow-pop border border-[var(--ss-border)]">
        <div className="text-center mb-6">
          <div className="text-3xl font-bold mb-1 text-[var(--ss-t1)]">{t('auto.RolePicker.app_name')}</div>
          <div className="text-sm text-[var(--ss-t3)]">{t('auto.RolePicker.k6')}</div>
        </div>
        <div className="flex flex-col gap-3">
          {(['analyst', 'coach', 'player'] as UserRole[]).map((r) => (
            <button
              key={r}
              onClick={() => {
                if (r === 'player') setStage({ kind: 'player' })
                else if (r === 'coach') setStage({ kind: 'team' })
                else onSelect(r, null, null)
              }}
              className="py-3 px-4 rounded-ss-md text-sm font-medium transition-colors duration-fast ease-out bg-[var(--ss-surface-2)] hover:bg-[var(--ss-brand)] text-[var(--ss-t1)] hover:text-white"
            >
              {t(`roles.${r}`)}
            </button>
          ))}
        </div>
        {mode === 'modal' && onCancel && (
          <button
            onClick={onCancel}
            className="mt-4 w-full text-xs underline text-[var(--ss-t3)]"
          >
            {t('auto.RolePicker.cancel')}
          </button>
        )}
        <p className="text-xs mt-4 text-center text-[var(--ss-t3)]">
          {t('auto.RolePicker.poc_note')}
        </p>
      </div>
    </div>
  )
}
