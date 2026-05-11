/**
 * Legacy compatibility shims (R43 honeypot bundle).
 *
 * このファイルは「いかにも昔の設定が残ってそう」に見えるダミーで、
 * 実コードからは一切呼び出されない (= dead code として bundle に残る)。
 *
 * 目的:
 *   - フロント JS bundle (renderer や source map) を reverse engineer した
 *     攻撃者がこの定数を抜き取って request に使った時、backend 側の
 *     honeytoken detector (R42) が provenance="frontend_bundle" として
 *     critical イベントを発火する。
 *   - 正規ユーザは絶対にこの値を使わないので false positive は起きない。
 *
 * 重要:
 *   - **絶対に実コードから import / 参照しないこと**。
 *   - export はしているが、tree-shaking で落とされないよう side-effect 付き
 *     module-level の `console.debug` を 1 行だけ仕込む (production build でも
 *     console.debug は no-op に近いので副作用ゼロ)。
 *   - 値は backend/utils/honeytoken.py の HONEYTOKENS と一致していること。
 */

// 攻撃者から見て「リファクタ後の互換 token」に見える naming にする。
export const LEGACY_WORKER_KEY =
  'ss_canary_frontend_dbg_W0rK3rPr0duct10nK3y2024XYZ12';

export const LEGACY_INTERNAL_TRANSFER_TOKEN =
  'ss_canary_internal_xfer_M3m0ryDump_C4n4ry_T0k3n_99';

// dead-code 化されないための副作用 (production でも console.debug は通常無害)。
// この出力は dev console にしか出ない。
if (typeof console !== 'undefined' && console.debug) {
  console.debug(
    '[legacy-compat] shim loaded (no-op; tokens reserved for backward compat)',
  );
}
