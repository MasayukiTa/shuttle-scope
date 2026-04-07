/**
 * WarmupNotesPanel — Set 1 前の公開練習観察メモパネル
 *
 * G3 spec: ANNOTATION_GUARD_AND_WARMUP_SPEC_v1.md §9
 *
 * 仕様:
 * - Set 1 / Rally 1 開始前にのみ表示
 * - チェックリスト/チップ形式（ライブ速度に依存しないため）
 * - 各フィールドに confidence_level セレクター付き
 * - モーダルではなくインラインパネル（blocking しない）
 * - 保存後は locked 状態（ラリー開始後は変更不可）
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { apiPost, apiGet } from '@/api/client'
import { WarmupConfidence, PreMatchObservation } from '@/types'

// 信頼度ラベル色
const CONFIDENCE_STYLE: Record<WarmupConfidence, string> = {
  unknown:   'bg-gray-700 text-gray-400 border-gray-600',
  tentative: 'bg-yellow-900/40 text-yellow-300 border-yellow-700/50',
  likely:    'bg-blue-900/40 text-blue-300 border-blue-700/50',
  confirmed: 'bg-green-900/40 text-green-300 border-green-700/50',
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
  locked: boolean
  onClose: () => void
}

export function WarmupNotesPanel({
  matchId,
  playerAId,
  playerBId,
  playerAName,
  playerBName,
  locked,
  onClose,
}: WarmupNotesPanelProps) {
  const { t } = useTranslation()

  // 選択中の選手タブ
  const [activePlayer, setActivePlayer] = useState<'player_a' | 'player_b'>('player_a')

  // 各観察フィールドの値・信頼度
  const initObs = (): PlayerObs => {
    const obs: PlayerObs = {}
    for (const def of OBS_TYPES) {
      obs[def.key] = { value: '', confidence: def.defaultConfidence }
    }
    return obs
  }
  const [obsA, setObsA] = useState<PlayerObs>(initObs)
  const [obsB, setObsB] = useState<PlayerObs>(initObs)

  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      // 両選手分の入力済みエントリをまとめてPOST
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

      const allObs = [
        ...buildObs(obsA, playerAId),
        ...buildObs(obsB, playerBId),
      ]

      if (allObs.length === 0) {
        onClose()
        return
      }

      await apiPost(`/warmup/observations/${matchId}`, { observations: allObs })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err: any) {
      setError(err?.message ?? '保存に失敗しました')
    } finally {
      setSaving(false)
    }
  }

  const playerName = activePlayer === 'player_a' ? playerAName : playerBName

  return (
    <div className="border border-blue-700/40 bg-blue-950/30 rounded p-3 text-xs space-y-3">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-blue-300 font-medium text-sm">{t('warmup.title')}</div>
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

      {/* ロック警告 */}
      {locked && (
        <div className="text-yellow-500 text-[11px] bg-yellow-900/20 border border-yellow-700/40 rounded px-2 py-1">
          {t('warmup.locked_hint')}
        </div>
      )}

      {/* 選手タブ */}
      <div className="flex gap-1.5">
        {(
          [
            { key: 'player_a' as const, name: playerAName, color: 'blue' },
            { key: 'player_b' as const, name: playerBName, color: 'orange' },
          ]
        ).map(({ key, name, color }) => (
          <button
            key={key}
            onClick={() => setActivePlayer(key)}
            className={clsx(
              'flex-1 py-1.5 rounded text-xs font-medium transition-colors',
              activePlayer === key
                ? color === 'blue'
                  ? 'bg-blue-600 text-white'
                  : 'bg-orange-600 text-white'
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
                        ? 'bg-blue-600 border-blue-500 text-white'
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

      {/* エラー */}
      {error && (
        <div className="text-red-400 text-[11px]">{error}</div>
      )}

      {/* 保存ボタン */}
      {!locked && (
        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className={clsx(
              'flex-1 py-1.5 rounded text-xs font-medium transition-colors',
              saved
                ? 'bg-green-700 text-white'
                : 'bg-blue-600 hover:bg-blue-500 text-white',
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
