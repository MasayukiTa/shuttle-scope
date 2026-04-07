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
 */
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { apiPost, apiGet } from '@/api/client'
import { WarmupConfidence, PreMatchObservation } from '@/types'

// 信頼度ボタンスタイル（gray スケール、色ルール準拠）
const CONFIDENCE_STYLE: Record<WarmupConfidence, string> = {
  unknown:   'bg-gray-700 text-gray-500 border-gray-600',
  tentative: 'bg-gray-600 text-gray-300 border-gray-500',
  likely:    'bg-gray-500 text-gray-200 border-gray-400',
  confirmed: 'bg-gray-400 text-gray-900 border-gray-300',
}

const CONFIDENCE_LEVELS: WarmupConfidence[] = ['unknown', 'tentative', 'likely', 'confirmed']

// 観察タイプ定義
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

// 自コンディション観察タイプ（player_a = self のみ）
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

interface WarmupNotesPanelProps {
  matchId: number
  playerAId: number
  playerBId: number
  playerAName: string
  playerBName: string
  playerAHand?: string
  playerBHand?: string
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
  locked,
  onClose,
}: WarmupNotesPanelProps) {
  const { t } = useTranslation()

  const [activePlayer, setActivePlayer] = useState<'player_a' | 'player_b'>('player_a')

  const [obsA, setObsA] = useState<PlayerObs>(() => initObs(playerAHand))
  const [obsB, setObsB] = useState<PlayerObs>(() => initObs(playerBHand))
  const [selfObs, setSelfObs] = useState<PlayerObs>(initSelfObs)

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
        const newSelfObs = initSelfObs()
        for (const o of resp.data) {
          const isObsType = OBS_TYPES.some((d) => d.key === o.observation_type)
          const isSelfType = SELF_OBS_TYPES.some((d) => d.key === o.observation_type)
          const conf = o.confidence_level as WarmupConfidence
          if (isObsType) {
            if (o.player_id === playerAId) {
              newObsA[o.observation_type] = { value: o.observation_value, confidence: conf }
            } else if (o.player_id === playerBId) {
              newObsB[o.observation_type] = { value: o.observation_value, confidence: conf }
            }
          } else if (isSelfType) {
            newSelfObs[o.observation_type] = { value: o.observation_value, confidence: conf }
          }
        }
        setObsA(newObsA)
        setObsB(newObsB)
        setSelfObs(newSelfObs)
      })
      .catch(() => {
        // サイレント失敗（データなし扱い）
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId])

  const currentObs = activePlayer === 'player_a' ? obsA : obsB
  const setCurrentObs = activePlayer === 'player_a' ? setObsA : setObsB
  const currentPlayerId = activePlayer === 'player_a' ? playerAId : playerBId

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
      const buildObs = (obs: PlayerObs, playerId: number): PreMatchObservation[] =>
        OBS_TYPES
          .filter((def) => obs[def.key]?.value)
          .map((def) => ({
            match_id: matchId,
            player_id: playerId,
            observation_type: def.key,
            observation_value: obs[def.key].value,
            confidence_level: obs[def.key].confidence,
            created_by: 'analyst',
          }))

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
        ...buildSelfObs(selfObs, playerAId),
      ]

      if (allObs.length > 0) {
        await apiPost(`/warmup/observations/${matchId}`, { observations: allObs })
      }
      setSaved(true)
      setTimeout(() => onClose(), 800)
    } catch (err: any) {
      setError(err?.message ?? '保存に失敗しました')
      setSaving(false)
    }
  }

  return (
    <div className="border border-gray-700 bg-gray-800 rounded p-3 text-xs space-y-3">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-gray-200 font-medium text-sm">{t('warmup.title')}</div>
          <div className="text-gray-500 mt-0.5">{t('warmup.subtitle')}</div>
        </div>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
          title={t('app.close')}
        >
          ✕
        </button>
      </div>

      {/* ロック警告（ラリー進行中のみ） */}
      {locked && (
        <div className="text-gray-400 text-[11px] bg-gray-700 border border-gray-600 rounded px-2 py-1">
          {t('warmup.locked_hint_rally', 'ラリー進行中は変更できません')}
        </div>
      )}

      {/* 選手タブ */}
      <div className="flex gap-1.5">
        {(
          [
            { key: 'player_a' as const, name: playerAName },
            { key: 'player_b' as const, name: playerBName },
          ]
        ).map(({ key, name }) => (
          <button
            key={key}
            onClick={() => setActivePlayer(key)}
            className={clsx(
              'flex-1 py-1.5 rounded text-xs font-medium transition-colors',
              activePlayer === key
                ? 'bg-gray-600 text-white'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600',
            )}
          >
            {name}
          </button>
        ))}
      </div>

      {/* 観察フィールド */}
      <div className="space-y-3">
        {OBS_TYPES.map((def) => {
          const entry = currentObs[def.key]
          return (
            <div key={def.key} className="space-y-1">
              {/* ラベル行 */}
              <div className="flex items-center justify-between">
                <span className="text-gray-300 font-medium">
                  {t(`warmup.observation_${def.key}`)}
                </span>
                {/* 信頼度セレクター */}
                <div className="flex gap-1">
                  {CONFIDENCE_LEVELS.map((lvl) => (
                    <button
                      key={lvl}
                      onClick={() => setConfidence(def.key, lvl)}
                      disabled={locked}
                      className={clsx(
                        'px-1.5 py-0.5 rounded border text-[10px] transition-colors',
                        entry.confidence === lvl
                          ? CONFIDENCE_STYLE[lvl]
                          : 'bg-gray-800 text-gray-600 border-gray-700 hover:text-gray-400',
                        locked && 'cursor-not-allowed opacity-50',
                      )}
                    >
                      {t(`warmup.confidence_${lvl}`)}
                    </button>
                  ))}
                </div>
              </div>

              {/* 値チップ */}
              <div className="flex flex-wrap gap-1">
                {def.values.map((val) => (
                  <button
                    key={val}
                    onClick={() => setField(def.key, entry.value === val ? '' : val)}
                    disabled={locked}
                    className={clsx(
                      'px-2 py-1 rounded border text-[11px] transition-colors',
                      entry.value === val
                        ? 'bg-gray-500 border-gray-400 text-white'
                        : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600',
                      locked && 'cursor-not-allowed opacity-50',
                    )}
                  >
                    {t(`warmup.value_${def.key}_${val}`)}
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {/* 自コンディション（player_a タブのみ表示） */}
      {activePlayer === 'player_a' && (
        <div className="border-t border-gray-700/60 pt-3 space-y-3">
          <div className="text-[11px] text-gray-400 font-medium">
            {t('warmup.self_condition_section', '自コンディション（任意）')}
          </div>
          {SELF_OBS_TYPES.map((def) => {
            const entry = selfObs[def.key]
            return (
              <div key={def.key} className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-gray-300 font-medium">
                    {t(`warmup.observation_${def.key}`, def.key)}
                  </span>
                  <div className="flex gap-1">
                    {CONFIDENCE_LEVELS.map((lvl) => (
                      <button
                        key={lvl}
                        onClick={() => {
                          if (locked) return
                          setSelfObs((prev) => ({
                            ...prev,
                            [def.key]: { ...prev[def.key], confidence: lvl },
                          }))
                          setSaved(false)
                        }}
                        disabled={locked}
                        className={clsx(
                          'px-1.5 py-0.5 rounded border text-[10px] transition-colors',
                          entry.confidence === lvl
                            ? CONFIDENCE_STYLE[lvl]
                            : 'bg-gray-800 text-gray-600 border-gray-700 hover:text-gray-400',
                          locked && 'cursor-not-allowed opacity-50',
                        )}
                      >
                        {t(`warmup.confidence_${lvl}`)}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  {def.values.map((val) => (
                    <button
                      key={val}
                      onClick={() => {
                        if (locked) return
                        setSelfObs((prev) => ({
                          ...prev,
                          [def.key]: { ...prev[def.key], value: prev[def.key].value === val ? '' : val },
                        }))
                        setSaved(false)
                      }}
                      disabled={locked}
                      className={clsx(
                        'px-2 py-1 rounded border text-[11px] transition-colors',
                        entry.value === val
                          ? 'bg-gray-500 border-gray-400 text-white'
                          : 'bg-gray-700 border-gray-600 text-gray-300 hover:bg-gray-600',
                        locked && 'cursor-not-allowed opacity-50',
                      )}
                    >
                      {t(`warmup.value_self_${def.key.replace('self_', '')}_${val}`, val)}
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* エラー */}
      {error && (
        <div className="text-red-400 text-[11px]">{error}</div>
      )}

      {/* 保存ボタン */}
      {!locked && (
        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving || saved}
            className={clsx(
              'flex-1 py-1.5 rounded text-xs font-medium transition-colors',
              saved
                ? 'bg-gray-600 text-gray-300 cursor-default'
                : 'bg-gray-600 hover:bg-gray-500 text-white',
              saving && 'opacity-60 cursor-not-allowed',
            )}
          >
            {saving ? '保存中…' : saved ? `✓ ${t('warmup.saved')}` : t('warmup.save')}
          </button>
          <button
            onClick={onClose}
            className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
          >
            {t('warmup.cancel')}
          </button>
        </div>
      )}
    </div>
  )
}
