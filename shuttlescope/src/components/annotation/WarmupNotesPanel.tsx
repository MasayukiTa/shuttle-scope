/**
 * WarmupNotesPanel — Set 1 前の公開練習観察メモパネル
 *
 * G3 spec: ANNOTATION_GUARD_AND_WARMUP_SPEC_v1.md §9
 *
 * 仕様:
 * - ラリー進行中はロック（isRallyActive のみ）
 * - チェックリスト/チップ形式（ライブ速度に依存しないため）
 * - 各フィールドに confidence_level セレクター付き
 * - モーダルではなくインラインパネル（blocking しない）
 * - 保存後はパネルを閉じる
 * - 既存データをマウント時に読み込む
 * - ダブルスは 4 選手分のタブを表示
 */
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { apiPost, apiGet } from '@/api/client'
import { WarmupConfidence, PreMatchObservation } from '@/types'
import { errorMessage } from '@/utils/errors'
import { MIcon } from '@/components/common/MIcon'

// 信頼度ボタンスタイル（選択時は常に text-white で視認性を確保）
const CONFIDENCE_STYLE: Record<WarmupConfidence, string> = {
  unknown:   'bg-[var(--ss-t3)] text-white border-[var(--ss-t3)]',
  tentative: 'bg-[var(--ss-warn)] text-white border-[var(--ss-warn)]',
  likely:    'bg-[var(--ss-emphasis)] text-white border-[var(--ss-emphasis)]',
  confirmed: 'bg-[var(--ss-brand)] text-white border-[var(--ss-brand)]',
}

const CONFIDENCE_LEVELS: WarmupConfidence[] = ['unknown', 'tentative', 'likely', 'confirmed']

interface ObsTypeDef {
  key: string
  values: string[]
  defaultConfidence: WarmupConfidence
}

const OBS_TYPES: ObsTypeDef[] = [
  {
    key: 'handedness',
    values: ['R', 'L', 'unknown'],
    defaultConfidence: 'likely',
  },
  {
    key: 'physical_caution',
    values: ['none', 'light', 'moderate', 'heavy'],
    defaultConfidence: 'likely',
  },
  {
    key: 'tactical_style',
    values: ['attacker', 'defender', 'balanced', 'unknown'],
    defaultConfidence: 'tentative',
  },
  {
    key: 'court_preference',
    values: ['front', 'rear', 'balanced', 'unknown'],
    defaultConfidence: 'tentative',
  },
]

const SELF_OBS_TYPES: ObsTypeDef[] = [
  {
    key: 'self_condition',
    values: ['great', 'normal', 'heavy', 'poor'],
    defaultConfidence: 'confirmed',
  },
  {
    key: 'self_timing',
    values: ['sharp', 'normal', 'off'],
    defaultConfidence: 'confirmed',
  },
]

interface PlayerObs {
  [obsType: string]: {
    value: string
    confidence: WarmupConfidence
  }
}

type PlayerKey = 'player_a' | 'partner_a' | 'partner_b' | 'player_b'

interface WarmupNotesPanelProps {
  matchId: number
  playerAId: number
  playerBId: number
  playerAName: string
  playerBName: string
  playerAHand?: string
  playerBHand?: string
  // doubles support
  partnerAId?: number
  partnerBId?: number
  partnerAName?: string
  partnerBName?: string
  locked: boolean
  onClose: () => void
}

function handToValue(hand?: string): string {
  if (!hand) return ''
  const h = hand.toLowerCase()
  if (h === 'right' || h === 'r') return 'R'
  if (h === 'left' || h === 'l') return 'L'
  return 'unknown'
}

function initObs(hand?: string): PlayerObs {
  const obs: PlayerObs = {}
  for (const def of OBS_TYPES) {
    obs[def.key] = { value: '', confidence: def.defaultConfidence }
  }
  const handVal = handToValue(hand)
  if (handVal) {
    obs['handedness'] = { value: handVal, confidence: 'likely' }
  }
  return obs
}

function initSelfObs(): PlayerObs {
  const obs: PlayerObs = {}
  for (const def of SELF_OBS_TYPES) {
    obs[def.key] = { value: '', confidence: def.defaultConfidence }
  }
  return obs
}

export function WarmupNotesPanel({
  matchId,
  playerAId,
  playerBId,
  playerAName,
  playerBName,
  playerAHand,
  playerBHand,
  partnerAId,
  partnerBId,
  partnerAName,
  partnerBName,
  locked,
  onClose,
}: WarmupNotesPanelProps) {
  const { t } = useTranslation()

  const isDoubles = !!(partnerAId && partnerBId)

  const [activePlayer, setActivePlayer] = useState<PlayerKey>('player_a')

  const [obsA, setObsA] = useState<PlayerObs>(() => initObs(playerAHand))
  const [obsPartnerA, setObsPartnerA] = useState<PlayerObs>(() => initObs())
  const [obsPartnerB, setObsPartnerB] = useState<PlayerObs>(() => initObs())
  const [obsB, setObsB] = useState<PlayerObs>(() => initObs(playerBHand))
  const [selfObs, setSelfObs] = useState<PlayerObs>(initSelfObs)
  const [selfObsPartnerA, setSelfObsPartnerA] = useState<PlayerObs>(initSelfObs)

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // マウント時に既存の観察データを読み込む
  useEffect(() => {
    apiGet<{ success: boolean; data: Array<{
      player_id: number
      observation_type: string
      observation_value: string
      confidence_level: string
    }> }>(`/warmup/observations/${matchId}`)
      .then((resp) => {
        if (!resp?.data?.length) return
        const newObsA = initObs(playerAHand)
        const newObsB = initObs(playerBHand)
        const newObsPartnerA = initObs()
        const newObsPartnerB = initObs()
        const newSelfObs = initSelfObs()
        const newSelfObsPartnerA = initSelfObs()
        for (const o of resp.data) {
          const isObsType = OBS_TYPES.some((d) => d.key === o.observation_type)
          const isSelfType = SELF_OBS_TYPES.some((d) => d.key === o.observation_type)
          const conf = o.confidence_level as WarmupConfidence
          if (isObsType) {
            if (o.player_id === playerAId) {
              newObsA[o.observation_type] = { value: o.observation_value, confidence: conf }
            } else if (o.player_id === playerBId) {
              newObsB[o.observation_type] = { value: o.observation_value, confidence: conf }
            } else if (partnerAId && o.player_id === partnerAId) {
              newObsPartnerA[o.observation_type] = { value: o.observation_value, confidence: conf }
            } else if (partnerBId && o.player_id === partnerBId) {
              newObsPartnerB[o.observation_type] = { value: o.observation_value, confidence: conf }
            }
          } else if (isSelfType) {
            if (o.player_id === playerAId) {
              newSelfObs[o.observation_type] = { value: o.observation_value, confidence: conf }
            } else if (partnerAId && o.player_id === partnerAId) {
              newSelfObsPartnerA[o.observation_type] = { value: o.observation_value, confidence: conf }
            }
          }
        }
        setObsA(newObsA)
        setObsB(newObsB)
        setObsPartnerA(newObsPartnerA)
        setObsPartnerB(newObsPartnerB)
        setSelfObs(newSelfObs)
        setSelfObsPartnerA(newSelfObsPartnerA)
      })
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId])

  const obsMap: Record<PlayerKey, PlayerObs> = {
    player_a: obsA,
    partner_a: obsPartnerA,
    partner_b: obsPartnerB,
    player_b: obsB,
  }
  const setObsMap: Record<PlayerKey, React.Dispatch<React.SetStateAction<PlayerObs>>> = {
    player_a: setObsA,
    partner_a: setObsPartnerA,
    partner_b: setObsPartnerB,
    player_b: setObsB,
  }
  const _idMap: Record<PlayerKey, number | undefined> = {
    player_a: playerAId,
    partner_a: partnerAId,
    partner_b: partnerBId,
    player_b: playerBId,
  }

  const currentObs = obsMap[activePlayer]
  const setCurrentObs = setObsMap[activePlayer]

  const setField = (obsType: string, value: string) => {
    if (locked) return
    setCurrentObs((prev) => ({
      ...prev,
      [obsType]: { ...prev[obsType], value },
    }))
    setSaved(false)
  }

  const setConfidence = (obsType: string, confidence: WarmupConfidence) => {
    if (locked) return
    setCurrentObs((prev) => ({
      ...prev,
      [obsType]: { ...prev[obsType], confidence },
    }))
    setSaved(false)
  }

  const handleSave = async () => {
    if (locked) return
    setSaving(true)
    setError(null)
    try {
      const buildObs = (obs: PlayerObs, playerId: number | undefined): PreMatchObservation[] => {
        if (!playerId) return []
        return OBS_TYPES
          .filter((def) => obs[def.key]?.value)
          .map((def) => ({
            match_id: matchId,
            player_id: playerId,
            observation_type: def.key,
            observation_value: obs[def.key].value,
            confidence_level: obs[def.key].confidence,
            created_by: 'analyst',
          }))
      }

      const buildSelfObs = (obs: PlayerObs, playerId: number): PreMatchObservation[] =>
        SELF_OBS_TYPES
          .filter((def) => obs[def.key]?.value)
          .map((def) => ({
            match_id: matchId,
            player_id: playerId,
            observation_type: def.key,
            observation_value: obs[def.key].value,
            confidence_level: obs[def.key].confidence,
            created_by: 'analyst',
          }))

      const allObs = [
        ...buildObs(obsA, playerAId),
        ...buildObs(obsB, playerBId),
        ...(isDoubles ? buildObs(obsPartnerA, partnerAId) : []),
        ...(isDoubles ? buildObs(obsPartnerB, partnerBId) : []),
        ...buildSelfObs(selfObs, playerAId),
        ...(isDoubles && partnerAId ? buildSelfObs(selfObsPartnerA, partnerAId) : []),
      ]

      if (allObs.length === 0) {
        // 何も入力されていない: API を呼ばないので「保存済み」を見せず、
        // 空である旨を伝えて開いたままにする (実際に保存していないのに成功表示しない)。
        setError(t('warmup.nothing_to_save', { defaultValue: '保存する観察がありません' }))
        setSaving(false)
        return
      }
      await apiPost(`/warmup/observations/${matchId}`, { observations: allObs })
      setSaved(true)
      setTimeout(() => onClose(), 800)
    } catch (err: unknown) {
      setError(errorMessage(err, t('warmup.save_failed')))
      setSaving(false)
    }
  }

  // タブ定義（シングルス: 2タブ、ダブルス: 4タブ）
  const tabs: Array<{ key: PlayerKey; label: string; teamLabel?: string }> = isDoubles
    ? [
        { key: 'player_a',   label: playerAName,          teamLabel: 'A' },
        { key: 'partner_a',  label: partnerAName ?? 'A2', teamLabel: 'A' },
        { key: 'partner_b',  label: partnerBName ?? 'B2', teamLabel: 'B' },
        { key: 'player_b',   label: playerBName,          teamLabel: 'B' },
      ]
    : [
        { key: 'player_a', label: playerAName },
        { key: 'player_b', label: playerBName },
      ]

  return (
    <div className="border border-[var(--ss-border)] bg-[var(--ss-surface-1)] rounded-ss-lg shadow-card p-3 text-xs space-y-3">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[var(--ss-t1)] font-medium text-sm">{t('warmup.title')}</div>
          <div className="text-[var(--ss-t3)] mt-0.5">{t('warmup.subtitle')}</div>
        </div>
        <button
          onClick={onClose}
          className="text-[var(--ss-t3)] hover:text-[var(--ss-t1)] text-lg leading-none px-1 transition-colors duration-fast ease-out"
          title={t('app.close')}
        >
          <MIcon name="close" size={18} />
        </button>
      </div>

      {/* ロック警告 */}
      {locked && (
        <div className="text-[var(--ss-t2)] text-[11px] bg-[var(--ss-surface-2)] border border-[var(--ss-border)] rounded-ss-sm px-2 py-1">
          {t('warmup.locked_hint_rally', 'ラリー進行中は変更できません')}
        </div>
      )}

      {/* 選手タブ（ダブルスは4タブ） */}
      {isDoubles ? (
        <div className="space-y-1">
          <div className="flex gap-0.5">
            {tabs.slice(0, 2).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActivePlayer(key)}
                className={clsx(
                  'flex-1 py-1 rounded-ss-sm text-[11px] font-medium transition-colors duration-fast ease-out truncate px-1',
                  activePlayer === key
                    ? 'bg-[var(--ss-brand)] text-white'
                    : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]',
                )}
                title={label}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-0.5">
            {tabs.slice(2, 4).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActivePlayer(key)}
                className={clsx(
                  'flex-1 py-1 rounded-ss-sm text-[11px] font-medium transition-colors duration-fast ease-out truncate px-1',
                  activePlayer === key
                    ? 'bg-[var(--ss-emphasis)] text-white'
                    : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]',
                )}
                title={label}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex justify-between text-[9px] text-[var(--ss-t3)] px-0.5">
            <span>{t('warmup.team_a')}</span>
            <span>{t('warmup.team_b')}</span>
          </div>
        </div>
      ) : (
        <div className="flex gap-1.5">
          {tabs.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActivePlayer(key)}
              className={clsx(
                'flex-1 py-1.5 rounded-ss-sm text-xs font-medium transition-colors duration-fast ease-out',
                activePlayer === key
                  ? 'bg-[var(--ss-brand)] text-white'
                  : 'bg-[var(--ss-surface-2)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* 観察フィールド */}
      <div className="space-y-2">
        {OBS_TYPES.map((def) => {
          const entry = currentObs[def.key]
          return (
            <div key={def.key} className="bg-[var(--ss-surface-2)] rounded-ss-md p-2 space-y-1.5">
              {/* 項目名（1行目） */}
              <span className="text-[var(--ss-t2)] font-medium text-[11px] block">
                {t(`warmup.observation_${def.key}`)}
              </span>
              {/* 選択値ボタン + 確からしさボタン（同じ行で高さ揃え） */}
              <div className="flex items-center gap-2">
                <div className="flex flex-wrap gap-1 flex-1">
                  {def.values.map((val) => (
                    <button
                      key={val}
                      onClick={() => setField(def.key, entry.value === val ? '' : val)}
                      disabled={locked}
                      className={clsx(
                        'px-2 py-1 rounded-ss-sm border text-[11px] transition-colors duration-fast ease-out',
                        entry.value === val
                          ? 'bg-[var(--ss-t2)] border-[var(--ss-t2)] text-white'
                          : 'bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]',
                        locked && 'cursor-not-allowed opacity-50',
                      )}
                    >
                      {t(`warmup.value_${def.key}_${val}`)}
                    </button>
                  ))}
                </div>
                <div className="flex gap-0.5 shrink-0">
                  {CONFIDENCE_LEVELS.map((lvl) => (
                    <button
                      key={lvl}
                      onClick={() => setConfidence(def.key, lvl)}
                      disabled={locked}
                      className={clsx(
                        'px-1.5 py-1 rounded-ss-sm border text-[10px] transition-colors duration-fast ease-out',
                        entry.confidence === lvl
                          ? CONFIDENCE_STYLE[lvl]
                          : 'bg-[var(--ss-surface-1)] text-[var(--ss-t3)] border-[var(--ss-border)] hover:text-[var(--ss-t2)]',
                        locked && 'cursor-not-allowed opacity-50',
                      )}
                      title={t(`warmup.confidence_${lvl}`)}
                    >
                      {t(`warmup.confidence_${lvl}`)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* 自コンディション（player_a タブ + ダブルスは partner_a タブも表示） */}
      {(activePlayer === 'player_a' || (isDoubles && activePlayer === 'partner_a')) && (() => {
        const isPartnerA = activePlayer === 'partner_a'
        const activeSelfObs = isPartnerA ? selfObsPartnerA : selfObs
        const setActiveSelfObs = isPartnerA ? setSelfObsPartnerA : setSelfObs
        return (
          <div className="border-t border-[var(--ss-border)] pt-3 space-y-2">
            <div className="text-[11px] text-[var(--ss-t2)] font-medium">
              {t('warmup.self_condition_section', '自コンディション（任意）')}
            </div>
            {SELF_OBS_TYPES.map((def) => {
              const entry = activeSelfObs[def.key]
              return (
                <div key={def.key} className="bg-[var(--ss-surface-2)] rounded-ss-md p-2 space-y-1.5">
                  <span className="text-[var(--ss-t2)] font-medium text-[11px] block">
                    {t(`warmup.observation_${def.key}`, def.key)}
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="flex flex-wrap gap-1 flex-1">
                      {def.values.map((val) => (
                        <button
                          key={val}
                          onClick={() => {
                            if (locked) return
                            setActiveSelfObs((prev) => ({
                              ...prev,
                              [def.key]: { ...prev[def.key], value: prev[def.key].value === val ? '' : val },
                            }))
                            setSaved(false)
                          }}
                          disabled={locked}
                          className={clsx(
                            'px-2 py-1 rounded-ss-sm border text-[11px] transition-colors duration-fast ease-out',
                            entry.value === val
                              ? 'bg-[var(--ss-t2)] border-[var(--ss-t2)] text-white'
                              : 'bg-[var(--ss-surface-1)] border-[var(--ss-border-strong)] text-[var(--ss-t2)] hover:bg-[var(--ss-surface-3)]',
                            locked && 'cursor-not-allowed opacity-50',
                          )}
                        >
                          {t(`warmup.value_self_${def.key.replace('self_', '')}_${val}`, val)}
                        </button>
                      ))}
                    </div>
                    <div className="flex gap-0.5 shrink-0">
                      {CONFIDENCE_LEVELS.map((lvl) => (
                        <button
                          key={lvl}
                          onClick={() => {
                            if (locked) return
                            setActiveSelfObs((prev) => ({
                              ...prev,
                              [def.key]: { ...prev[def.key], confidence: lvl },
                            }))
                            setSaved(false)
                          }}
                          disabled={locked}
                          className={clsx(
                            'px-1.5 py-1 rounded-ss-sm border text-[10px] transition-colors duration-fast ease-out',
                            entry.confidence === lvl
                              ? CONFIDENCE_STYLE[lvl]
                              : 'bg-[var(--ss-surface-1)] text-[var(--ss-t3)] border-[var(--ss-border)] hover:text-[var(--ss-t2)]',
                            locked && 'cursor-not-allowed opacity-50',
                          )}
                          title={t(`warmup.confidence_${lvl}`)}
                        >
                          {t(`warmup.confidence_${lvl}`)}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )
      })()}

      {/* エラー */}
      {error && (
        <div className="text-[var(--ss-bad)] text-[11px]">{error}</div>
      )}

      {/* 保存ボタン */}
      {!locked && (
        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving || saved}
            className={clsx(
              'flex-1 py-1.5 rounded-ss-md text-xs font-medium transition-colors duration-fast ease-out',
              saved
                ? 'bg-[var(--ss-surface-3)] text-[var(--ss-t2)] cursor-default'
                : 'bg-[var(--ss-brand)] hover:bg-[var(--ss-brand-hover)] text-white',
              saving && 'opacity-60 cursor-not-allowed',
            )}
          >
            {saving ? t('warmup.saving') : saved ? (<span className="inline-flex items-center gap-1"><MIcon name="check" size={12} />{t('warmup.saved')}</span>) : t('warmup.save')}
          </button>
          <button
            onClick={onClose}
            className="px-3 py-1.5 bg-[var(--ss-surface-2)] hover:bg-[var(--ss-surface-3)] text-[var(--ss-t2)] rounded-ss-md text-xs transition-colors duration-fast ease-out"
          >
            {t('warmup.cancel')}
          </button>
        </div>
      )}
    </div>
  )
}
