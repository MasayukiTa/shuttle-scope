/**
 * 最低標本数の判定 (監査 #438)。
 *
 * 防ぐ事象: NoDataMessage の minRequired は「あと何件で表示できます」の目安を出すだけで、
 * 描画を止める働きはない。呼び出し側が「0 件か」だけで分岐すると、1〜2 件でも
 * グラフや結果が出てしまい、公開トップの「少ないときは断定しません」と食い違う。
 * カードは描画の前にこの関数で必ず判定し、足りないときは NoDataMessage を出す。
 */
export function hasSufficientSample(sampleSize: number, minRequired: number): boolean {
  return Number.isFinite(sampleSize) && sampleSize >= minRequired
}
