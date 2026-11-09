// F-T003-05: 映像なしモードでのキャリブレーション導線の状態判定。
//
// 記録画面の設定タブ「キャリブレーションを開く」を押すと courtGridVisible が
// true になるが、映像なしモードでは「開けるか / 開けないなら理由」が UI 側の
// 複数条件に散らばっていた。押しても何も起きず理由も出ないケース
// (matchId 無し / 別モニタ再生中) があったため、判定を 1 つの純粋関数に集約し
// テストで固定する。
//
// 戻り値の意味:
//   'calib'            — 映像なしキャリブレーション画面 (6 点合わせ) を開く
//   'blocked_external' — 別モニタ再生中のため開けない。理由と導線を出す
//   'blocked_no_match' — 試合が未保存 (matchId 無し) のため開けない。理由を出す
//   'hint'             — ボタン未押下。従来どおり案内テキストのみ

export type NoVideoCalibState =
  | 'calib'
  | 'blocked_external'
  | 'blocked_no_match'
  | 'hint'

export interface NoVideoCalibInput {
  /** 設定タブの「キャリブレーションを開く」が押されているか */
  courtGridVisible: boolean
  /** URL params 由来の試合 ID。未保存の新規記録などでは undefined になり得る */
  matchId: string | undefined
  /** 別モニタ (video-only ウィンドウ) で再生中か */
  videoWindowOpen: boolean
}

/**
 * 映像なしモードでキャリブレーション領域に何を表示すべきかを判定する。
 *
 * courtGridVisible が false のときは常に 'hint' (従来の案内テキスト)。
 * true のときは、開けない理由がある場合にその理由を、無ければ 'calib' を返す。
 * 別モニタ再生中は校正キャンバスと競合するため 'blocked_external' を優先する。
 */
export function noVideoCalibState(input: NoVideoCalibInput): NoVideoCalibState {
  const { courtGridVisible, matchId, videoWindowOpen } = input
  if (!courtGridVisible) return 'hint'
  if (videoWindowOpen) return 'blocked_external'
  if (!matchId) return 'blocked_no_match'
  return 'calib'
}
