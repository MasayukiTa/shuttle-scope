/**
 * コンディション指標ごとの「良い方向」(監査 #348)。
 *
 * 防ぐ事象: 試合前後の変化 (後 − 前) を全指標一律に「増加 = 良い (青)」と塗ると、
 * 値が高いほど状態が悪い指標 (F1〜F5 の合計・Hooper Index) の悪化が青で出てしまう。
 *
 * 根拠: backend/analysis/condition_scoring.py で F1〜F5 は「高値=不良」(8〜40)、
 * ccs = 200 - total は「高値=良好」。Hooper Index は 4〜28 で高いほど状態悪化
 * (ConditionGlossary の説明も同じ)。
 */
const HIGHER_IS_BETTER: Record<string, boolean> = {
  ccs: true,
  f1: false,
  f2: false,
  f3: false,
  f4: false,
  f5: false,
  hooper_index: false,
}

/** 差分 (後 − 前) が良い方向への変化か。0 は悪化とみなさない。未知の指標は「増加 = 良い」。 */
export function isConditionImprovement(key: string, delta: number): boolean {
  return (HIGHER_IS_BETTER[key] ?? true) ? delta >= 0 : delta <= 0
}
