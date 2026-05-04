/**
 * ShotTypePanel — コンテキスト適応型ショット種別パネル
 *
 * バドミントンのルールと直前のショット種別に基づき、
 * - 絶対に起こりえないショットを非表示にする
 * - 最も可能性の高い返球候補を上位に表示する
 *
 * 【フィルタリングルール】
 * stroke_num === 1   : サービスのみ表示（ルール上サービスで始まる）
 * stroke_num >= 2    : サービスは常に非表示
 * ネット前返球後     : clear / around_head / slice を非表示
 *                      （これらはバック後方のポジションが必要）
 *
 * ネット前返球 = net_shot, cross_net, push_rush, flick, block, drop
 */
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { ShotType } from '@/types'
import { getStyleForShot } from '@/constants/shotTypeColors'

interface ShotTypePanelProps {
  selected: ShotType | null
  onSelect: (shotType: ShotType) => void
  disabled?: boolean
  /** 現在入力中のストローク番号（1 = サービス） */
  strokeNum: number
  /** 直前に確定したショット種別（最初のストロークは null） */
  lastShotType: ShotType | null
  /** K-001: 試合中モード — 2カラム・大きめボタン */
  isMatchDayMode?: boolean
}

// ─── キーボードショートカットマップ（useKeyboard.ts と同期すること） ──────────
// cant_reach はショット種別ではなくエンドタイプとして扱うため削除
// テンキー数字（1-9）はShotTypePanelでは扱わない（落点入力に使用）
// around_head は a→ショットキーなし（rally_end の A=勝者と衝突を避けるため）
// around_head は W キーで is_around_head 属性トグルとして扱う
// other は G キー（0は落点スキップに使用）
const KEYBOARD_MAP: Record<string, ShotType> = {
  '1': 'short_service', '2': 'long_service',
  'n': 'net_shot',     'c': 'clear',       'p': 'push_rush',
  's': 'smash',        'd': 'defensive',   'v': 'drive',
  'l': 'lob',          'o': 'drop',        'x': 'cross_net',
  'z': 'slice',
  'f': 'flick',        'h': 'half_smash',  'b': 'block',      'g': 'other',
}

// ─── コンテキスト判定 ───────────────────────────────────────────────────────

/** ネット前のポジションで返球するショット種別 */
const NET_ZONE_SHOTS = new Set<ShotType>([
  'net_shot', 'cross_net', 'push_rush', 'flick', 'block', 'drop',
])

/** バック後方の攻撃ショット（速い／沈む系） */
const BACK_ATTACK_SHOTS = new Set<ShotType>([
  'smash', 'half_smash', 'around_head',
])

/** バック後方の中立〜守備系ショット（高い弧線系） */
const BACK_NEUTRAL_SHOTS = new Set<ShotType>([
  'clear', 'lob', 'long_service', 'slice',
])

type ShotContext =
  | 'service'           // stroke 1: サービス確定
  | 'after_net'         // ネット前交換後
  | 'after_back_attack' // バック攻撃（スマッシュ等）後
  | 'after_back_neutral'// バック高打（クリア/ロブ等）後
  | 'neutral'           // ドライブ/守備/その他

function getShotContext(strokeNum: number, lastShotType: ShotType | null): ShotContext {
  if (strokeNum === 1) return 'service'
  if (!lastShotType) return 'neutral'
  if (NET_ZONE_SHOTS.has(lastShotType)) return 'after_net'
  if (BACK_ATTACK_SHOTS.has(lastShotType)) return 'after_back_attack'
  if (BACK_NEUTRAL_SHOTS.has(lastShotType)) return 'after_back_neutral'
  return 'neutral'
}

// ─── グループ定義 ────────────────────────────────────────────────────────────

type ShotGroup = { labelKey: string; shots: ShotType[] }

/**
 * コンテキストに応じたショットグループを返す。
 * 非表示ショットはそもそも含まれない（後段での filter 不要）。
 */
function buildGroups(context: ShotContext): ShotGroup[] {
  switch (context) {

    case 'service':
      // stroke 1: サービスのみ
      return [
        { labelKey: 'shot_categories.serve', shots: ['short_service', 'long_service'] },
      ]

    case 'after_net':
      // ネット前交換後。応答者はネット付近にいる。
      // 非表示: clear, around_head, slice（バック後方ポジション必須）
      return [
        { labelKey: 'shot_categories.net',        shots: ['net_shot', 'push_rush', 'cross_net', 'flick', 'block'] },
        { labelKey: 'shot_categories.attack_lob',  shots: ['smash', 'half_smash', 'lob', 'drive', 'defensive'] },
        { labelKey: 'shot_categories.special',     shots: ['other'] },
      ]

    case 'after_back_attack':
      // スマッシュ/ハーフスマッシュ/アラウンドヘッド後。受け側優先。
      return [
        { labelKey: 'shot_categories.defend',      shots: ['defensive', 'lob', 'drive', 'clear', 'block'] },
        { labelKey: 'shot_categories.net',         shots: ['net_shot', 'push_rush', 'cross_net', 'flick'] },
        { labelKey: 'shot_categories.back',        shots: ['smash', 'half_smash', 'drop', 'around_head', 'slice'] },
        { labelKey: 'shot_categories.special',     shots: ['other'] },
      ]

    case 'after_back_neutral':
      // クリア/ロブ/スライス後。バック系攻撃が最有力。
      return [
        { labelKey: 'shot_categories.back_attack', shots: ['smash', 'half_smash', 'drop', 'around_head', 'clear', 'slice'] },
        { labelKey: 'shot_categories.drive_defend',shots: ['drive', 'lob', 'defensive', 'block'] },
        { labelKey: 'shot_categories.net',         shots: ['net_shot', 'push_rush', 'cross_net', 'flick'] },
        { labelKey: 'shot_categories.special',     shots: ['other'] },
      ]

    case 'neutral':
    default:
      // ドライブ/守備/その他、または初期状態
      return [
        { labelKey: 'shot_categories.net',  shots: ['net_shot', 'push_rush', 'cross_net', 'flick', 'block'] },
        { labelKey: 'shot_categories.back', shots: ['smash', 'half_smash', 'clear', 'drop', 'around_head', 'slice'] },
        { labelKey: 'shot_categories.mid',  shots: ['drive', 'lob', 'defensive'] },
        { labelKey: 'shot_categories.special', shots: ['other'] },
      ]
  }
}

// ─── コンポーネント ──────────────────────────────────────────────────────────

export function ShotTypePanel({ selected, onSelect, disabled = false, strokeNum, lastShotType, isMatchDayMode = false }: ShotTypePanelProps) {
  const { t } = useTranslation()

  const context = getShotContext(strokeNum, lastShotType)
  const groups = buildGroups(context)

  return (
    <div className="flex flex-col gap-2">
      {groups.map((group) => (
        <div key={group.labelKey}>
          <div className="text-xs text-gray-500 mb-1 px-1">{t(group.labelKey)}</div>
          <div className={clsx('grid gap-1', isMatchDayMode ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-3')}>
            {group.shots.map((type) => {
              const key = Object.entries(KEYBOARD_MAP).find(([, v]) => v === type)?.[0] ?? ''
              // Phase B: ショット種別ごとに固定カテゴリ色を適用
              const style = getStyleForShot(type)
              const isSelected = selected === type
              return (
                <button
                  key={type}
                  onClick={() => !disabled && onSelect(type)}
                  disabled={disabled}
                  aria-pressed={isSelected}
                  className={clsx(
                    'relative px-2 rounded font-medium transition-colors border',
                    isMatchDayMode ? 'py-3 text-sm' : 'py-3 text-sm md:py-1.5 md:text-xs',
                    style.bg, style.bgHover, style.text, style.border,
                    isSelected && style.ringSelected,
                    disabled && 'opacity-40 cursor-not-allowed'
                  )}
                  title={`${t(`shot_types.${type}`)} (${key.toUpperCase()})`}
                >
                  <span className="absolute top-0.5 right-1 text-[9px] opacity-60 font-mono hidden md:inline">{key.toUpperCase()}</span>
                  <span className="absolute top-0.5 left-1 text-[10px] opacity-80" aria-hidden>{style.icon}</span>
                  <span className="block text-center leading-tight">{t(`shot_types.${type}`)}</span>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * 現在のコンテキストで有効なショット種別セットを返す。
 * useKeyboard.ts がキーガードに使用する。
 */
export function getValidShotTypes(strokeNum: number, lastShotType: ShotType | null): Set<ShotType> {
  const context = getShotContext(strokeNum, lastShotType)
  const groups = buildGroups(context)
  return new Set(groups.flatMap((g) => g.shots))
}

export { KEYBOARD_MAP }
