/**
 * shotSuggestion — 現ラリー内の実入力履歴に基づくショット候補の並べ替え。
 *
 * 背景:
 *   ShotTypePanel の buildGroups は「直前ショット種別に基づくコンテキスト
 *   フィルタ」までは行うが、グループ内の並び順は固定配列でハードコードされて
 *   おり、実際にそのラリーで繰り返し選ばれているショットが上位に来ない。
 *
 * 本モジュールは、現在入力中のラリー (currentStrokes) だけを材料に、
 *   (直前ショット種別 lastShotType の「次」に実際に選ばれた shot_type)
 * の出現回数を数え、各グループの shots を頻度降順で安定ソートする純関数を
 * 提供する。外部送信・推論モデル・個人データの持ち出しは一切しない
 * (集計元はフロントが保持する現ラリーの配列のみ)。
 *
 * コンテキストフィルタ (不可能ショットの除外) は buildGroups 側の責務であり、
 * ここでは「与えられたグループ内の順序」だけを変える。表示されない種別の
 * 統計で順序が乱れないよう、グループに含まれない種別のカウントは無視する。
 */
import type { ShotType } from '@/types'

/** ShotTypePanel.buildGroups が返すグループ。shots の順序のみ本モジュールで変える。 */
export interface ShotGroup {
  labelKey: string
  shots: ShotType[]
}

/** shot_type を持つ最小の入力レコード (StrokeInput / Stroke 双方を受けられる形)。 */
export interface ShotTypeRecord {
  shot_type: ShotType
}

/**
 * 現ラリーのストローク列から「lastShotType の直後に選ばれた shot_type」の
 * 出現回数を数える。strokes の隣接ペア (i, i+1) を走査し、strokes[i] の
 * shot_type が lastShotType に一致するとき strokes[i+1] の shot_type を 1 加算。
 *
 * lastShotType が null (= ラリー先頭、直前なし) の場合は空集計を返す。
 */
export function countNextShotTransitions(
  strokes: ReadonlyArray<ShotTypeRecord>,
  lastShotType: ShotType | null,
): Map<ShotType, number> {
  const counts = new Map<ShotType, number>()
  if (!lastShotType) return counts
  for (let i = 0; i + 1 < strokes.length; i++) {
    if (strokes[i].shot_type !== lastShotType) continue
    const next = strokes[i + 1].shot_type
    counts.set(next, (counts.get(next) ?? 0) + 1)
  }
  return counts
}

/**
 * 1 グループ内の shots を頻度降順で安定ソートする。
 * - counts の多い順。
 * - 同数 (0 を含む) は元の配列順を保持する (安定ソート)。
 * 新しい配列を返し、入力は破壊しない。
 */
export function sortGroupByCounts(
  shots: ReadonlyArray<ShotType>,
  counts: Map<ShotType, number>,
): ShotType[] {
  return shots
    .map((shot, index) => ({ shot, index, count: counts.get(shot) ?? 0 }))
    .sort((a, b) => (b.count - a.count) || (a.index - b.index))
    .map((e) => e.shot)
}

/** rankShotGroups の結果。 */
export interface RankedShotGroups {
  /** 並べ替え後のグループ (shots が頻度降順)。 */
  groups: ShotGroup[]
  /**
   * 最も多く選ばれた「次ショット」。count>0 の最大が一意または先勝ちで 1 件。
   * 表示上の★印対象。該当なし (履歴が無い / lastShotType が null) は null。
   * 与えられたグループに含まれない種別は候補にしない。
   */
  topSuggestion: ShotType | null
}

/**
 * 現ラリー履歴に基づき、全グループの shots を頻度降順に並べ替え、
 * 最多の次ショット (topSuggestion) を求める純関数。
 *
 * - 履歴が無い / lastShotType が null の場合は、groups をそのまま
 *   (順序不変で) 返し topSuggestion は null。既存挙動と完全に後方互換。
 * - topSuggestion はグループに実在する種別のうち count が最大のもの。
 *   同数は最初に現れたグループ・位置のものを採用 (決定的)。
 */
export function rankShotGroups(
  groups: ReadonlyArray<ShotGroup>,
  strokes: ReadonlyArray<ShotTypeRecord>,
  lastShotType: ShotType | null,
): RankedShotGroups {
  const counts = countNextShotTransitions(strokes, lastShotType)

  if (counts.size === 0) {
    // 変更を加えない (shots 配列は元参照のまま、ただし新しいグループ配列で包む)。
    return { groups: groups.map((g) => ({ ...g, shots: [...g.shots] })), topSuggestion: null }
  }

  const ranked = groups.map((g) => ({ ...g, shots: sortGroupByCounts(g.shots, counts) }))

  // topSuggestion: グループに実在する種別の中で count 最大のもの。
  let top: ShotType | null = null
  let topCount = 0
  for (const g of ranked) {
    for (const shot of g.shots) {
      const c = counts.get(shot) ?? 0
      if (c > topCount) {
        topCount = c
        top = shot
      }
    }
  }

  return { groups: ranked, topSuggestion: top }
}
