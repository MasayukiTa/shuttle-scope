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
import { MIcon } from '@/components/common/MIcon'
import { getStyleForShot } from '@/constants/shotTypeColors'
import {
  MAJOR_SHOTS,
  MAJOR_SHOT_JA,
  majorOf,
  representativeOf,
  type MajorShot,
} from '@/constants/shotMajorCategories'
import { rankShotGroups, type ShotTypeRecord } from './shotSuggestion'

interface ShotTypePanelProps {
  selected: ShotType | null
  onSelect: (shotType: ShotType) => void
  disabled?: boolean
  /** 現在入力中のストローク番号（1 = サービス） */
  strokeNum: number
  /** 直前に確定したショット種別（最初のストロークは null） */
  lastShotType: ShotType | null
  /**
   * 現在入力中のラリーのストローク列（省略可）。渡された場合、直前ショット
   * 種別の「次」に実際に選ばれた頻度でグループ内のタイル順を並べ替え、最多候補
   * に★印を付ける。省略時は従来どおり固定順（後方互換）。集計はこの配列のみ
   * を用い、外部送信や推論モデルは使わない。
   */
  strokes?: ReadonlyArray<ShotTypeRecord>
  /** K-001: 試合中モード — 2カラム・大きめボタン */
  isMatchDayMode?: boolean
  /** モバイルでも常にキーヒントを表示する (BT keyboard 接続の iPad 等) */
  forceShowKeyHints?: boolean
  /**
   * 簡易入力モード。true のとき 9 大分類タイルを表示し、
   * 選ぶと代表 canonical 小分類 (representativeOf) を onSelect に渡す。
   */
  simpleMode?: boolean
}

// ─── キーボードショートカットマップ（useKeyboard.ts と同期すること） ──────────
// cant_reach はショット種別ではなくエンドタイプとして扱うため削除
// テンキー数字（1-9）はShotTypePanelでは扱わない（落点入力に使用）
// around_head は a→ショットキーなし（rally_end の A=勝者と衝突を避けるため）
// around_head は W キーで is_around_head 属性トグルとして扱う
// other は G キー（0は落点スキップに使用）
//
// スマッシュ統合 (2026-11): 入力では smash 系を 1 つの 's'=smash に束ねる。
// 以前あった 'h'=half_smash は廃止し、around_head もショット種別としては
// 選べない（W キーの is_around_head 属性トグルは従来どおり残す）。保存値は
// canonical "smash" 固定。half_smash / around_head という canonical 値は
// 既存行・解析のために温存され (shot_taxonomy.py)、新規入力でのみ出なくなる。
const KEYBOARD_MAP: Record<string, ShotType> = {
  '1': 'short_service', '2': 'long_service',
  'n': 'net_shot',     'c': 'clear',       'p': 'push_rush',
  's': 'smash',        'd': 'defensive',   'v': 'drive',
  'l': 'lob',          'o': 'drop',        'x': 'cross_net',
  'z': 'slice',
  'f': 'flick',        'b': 'block',      'g': 'other',
}

// ─── コンテキスト判定 ───────────────────────────────────────────────────────

/** ネット前のポジションで返球するショット種別 */
const NET_ZONE_SHOTS = new Set<ShotType>([
  'net_shot', 'cross_net', 'push_rush', 'flick', 'block', 'drop',
])

/** バック後方の攻撃ショット（速い／沈む系）。
 *  入力からは smash に統合したが、既存行の lastShotType には half_smash /
 *  around_head が残り得るため、文脈判定ではそれらも後方攻撃として受理する。 */
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
        { labelKey: 'shot_categories.attack_lob',  shots: ['smash', 'lob', 'drive', 'defensive'] },
        { labelKey: 'shot_categories.special',     shots: ['other'] },
      ]

    case 'after_back_attack':
      // スマッシュ/ハーフスマッシュ/アラウンドヘッド後。受け側優先。
      return [
        { labelKey: 'shot_categories.defend',      shots: ['defensive', 'lob', 'drive', 'clear', 'block'] },
        { labelKey: 'shot_categories.net',         shots: ['net_shot', 'push_rush', 'cross_net', 'flick'] },
        { labelKey: 'shot_categories.back',        shots: ['smash', 'drop', 'slice'] },
        { labelKey: 'shot_categories.special',     shots: ['other'] },
      ]

    case 'after_back_neutral':
      // クリア/ロブ/スライス後。バック系攻撃が最有力。
      return [
        { labelKey: 'shot_categories.back_attack', shots: ['smash', 'drop', 'clear', 'slice'] },
        { labelKey: 'shot_categories.drive_defend',shots: ['drive', 'lob', 'defensive', 'block'] },
        { labelKey: 'shot_categories.net',         shots: ['net_shot', 'push_rush', 'cross_net', 'flick'] },
        { labelKey: 'shot_categories.special',     shots: ['other'] },
      ]

    case 'neutral':
    default:
      // ドライブ/守備/その他、または初期状態
      return [
        { labelKey: 'shot_categories.net',  shots: ['net_shot', 'push_rush', 'cross_net', 'flick', 'block'] },
        { labelKey: 'shot_categories.back', shots: ['smash', 'clear', 'drop', 'slice'] },
        { labelKey: 'shot_categories.mid',  shots: ['drive', 'lob', 'defensive'] },
        { labelKey: 'shot_categories.special', shots: ['other'] },
      ]
  }
}

// ─── コンポーネント ──────────────────────────────────────────────────────────

export function ShotTypePanel({ selected, onSelect, disabled = false, strokeNum, lastShotType, strokes, isMatchDayMode = false, forceShowKeyHints = false, simpleMode = false }: ShotTypePanelProps) {
  const { t } = useTranslation()

  // 簡易モード: 9 大分類タイル。選ぶと代表 canonical 小分類を onSelect に渡す。
  // 選択中ハイライトは「選ばれている shot_type が属する大分類」を点灯する。
  if (simpleMode) {
    const validMajors = getValidMajorShots(strokeNum)
    const selectedMajor: MajorShot | null = selected ? majorOf(selected) : null
    const majors = MAJOR_SHOTS.filter((m) => validMajors.has(m))
    return (
      <div className="flex flex-col gap-2" data-tutorial="annotator.shotTypes">
        <div className={clsx('grid gap-1', isMatchDayMode ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-3')}>
          {majors.map((major) => {
            const rep = representativeOf(major)
            const key = Object.entries(MAJOR_KEYBOARD_MAP).find(([, v]) => v === major)?.[0] ?? ''
            const style = getStyleForShot(rep)
            const isSelected = selectedMajor === major
            const label = t(`shot_major.${major}`, { defaultValue: MAJOR_SHOT_JA[major] })
            return (
              <button
                key={major}
                data-tile="true"
                data-major={major}
                onClick={() => !disabled && onSelect(rep)}
                disabled={disabled}
                aria-pressed={isSelected}
                className={clsx(
                  'relative px-2 rounded-ss-md font-medium transition-colors border',
                  isMatchDayMode ? 'py-3 text-sm' : 'py-3 text-sm md:py-1.5 md:text-xs',
                  style.bg, style.bgHover, style.text, style.border,
                  isSelected && style.ringSelected,
                  disabled && 'opacity-40 cursor-not-allowed'
                )}
                title={`${label} (${key.toUpperCase()})`}
              >
                <span className={clsx('absolute top-0.5 right-1 text-[9px] ss-num opacity-60 font-mono', forceShowKeyHints ? 'inline' : 'hidden md:inline')}>{key.toUpperCase()}</span>
                <span className="absolute top-0.5 left-1 text-[10px] opacity-80" aria-hidden>{style.icon}</span>
                <span className="block text-center leading-tight">{label}</span>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  const context = getShotContext(strokeNum, lastShotType)
  // 現ラリー履歴 (strokes) が渡された場合のみ、直前ショット種別の「次」に実際に
  // 選ばれた頻度でグループ内の順序を並べ替え、最多候補に★印を付ける。省略時は
  // topSuggestion=null・順序不変で従来挙動を維持する。
  const { groups, topSuggestion } = rankShotGroups(buildGroups(context), strokes ?? [], lastShotType)

  return (
    <div className="flex flex-col gap-2" data-tutorial="annotator.shotTypes">
      {groups.map((group) => (
        <div key={group.labelKey}>
          <div className="text-xs text-[var(--ss-t3)] mb-1 px-1">{t(group.labelKey)}</div>
          <div className={clsx('grid gap-1', isMatchDayMode ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-3')}>
            {group.shots.map((type) => {
              const key = Object.entries(KEYBOARD_MAP).find(([, v]) => v === type)?.[0] ?? ''
              // Phase B: ショット種別ごとに固定カテゴリ色を適用
              const style = getStyleForShot(type)
              const isSelected = selected === type
              const isTop = topSuggestion === type
              return (
                <button
                  key={type}
                  data-tile="true"
                  data-top-suggestion={isTop ? 'true' : undefined}
                  onClick={() => !disabled && onSelect(type)}
                  disabled={disabled}
                  aria-pressed={isSelected}
                  className={clsx(
                    'relative px-2 rounded-ss-md font-medium transition-colors border',
                    isMatchDayMode ? 'py-3 text-sm' : 'py-3 text-sm md:py-1.5 md:text-xs',
                    style.bg, style.bgHover, style.text, style.border,
                    isSelected && style.ringSelected,
                    disabled && 'opacity-40 cursor-not-allowed'
                  )}
                  title={`${t(`shot_types.${type}`)} (${key.toUpperCase()})${isTop ? ` — ${t('annotator.shot_suggestion_top')}` : ''}`}
                >
                  <span className={clsx('absolute top-0.5 right-1 text-[9px] ss-num opacity-60 font-mono', forceShowKeyHints ? 'inline' : 'hidden md:inline')}>{key.toUpperCase()}</span>
                  <span className="absolute top-0.5 left-1 text-[10px] opacity-80" aria-hidden>{style.icon}</span>
                  {isTop && (
                    <MIcon
                      name="star"
                      fill={1}
                      size={10}
                      className="absolute bottom-0.5 right-1 leading-none text-[var(--ss-warn)]"
                      ariaLabel={t('annotator.shot_suggestion_top')}
                    />
                  )}
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

// ─── 簡易モード（9 大分類） ─────────────────────────────────────────────
//
// 大分類キーマップ。KEYBOARD_MAP の小分類キーとは独立に定義する。
// useKeyboard.ts が simpleMode 時にこちらを引く。キーは小分類側の
// 代表文字と揃える（serve=s は smash と衝突するため 1/2 をサーブに割当）。
const MAJOR_KEYBOARD_MAP: Record<string, MajorShot> = {
  '1': 'serve',
  'n': 'net',
  'o': 'drop',
  'c': 'clear',
  's': 'smash',
  'v': 'drive',
  'l': 'lob',
  'd': 'defensive',
  'g': 'other',
}

/**
 * 簡易モードで現在有効な大分類セット。
 * 1 球目はサーブのみ。2 球目以降はサーブを除く残り 8 種。
 * (18 分類側の「サーブはラリー 1 球目のみ」制約と整合させる)
 */
export function getValidMajorShots(strokeNum: number): Set<MajorShot> {
  if (strokeNum === 1) return new Set<MajorShot>(['serve'])
  return new Set<MajorShot>(MAJOR_SHOTS.filter((m) => m !== 'serve'))
}

export { KEYBOARD_MAP, MAJOR_KEYBOARD_MAP }
