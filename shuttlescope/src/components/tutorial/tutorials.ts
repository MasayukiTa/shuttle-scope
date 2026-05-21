/**
 * 全ユーザ共通のチュートリアル定義。
 *
 * 表示ポリシー: role に関係なく同じステップを表示する (運用シンプル優先)。
 * 一部 step が player には機能的に見えなくても、説明として読める内容にする。
 */
import type { TutorialDef } from './TutorialOverlay'

export const TUTORIALS: Record<string, TutorialDef> = {
  mobile_annotate_pass: {
    id: 'mobile_annotate_pass',
    title: 'モバイルでのアノテーション (Pass 1→2→3)',
    steps: [
      { title: 'モバイルでの 3-pass 入力',
        body: 'モバイルでは「ラリー区切り」「サーブ+最終打」「ストローク詳細」を 3 つのパスに分けて入力します。1 試合をいきなり全部やる必要はなく、後でデスクトップで仕上げてもかまいません。' },
      { title: 'Pass 切替ボタン',
        target: '[data-tutorial="mobileAnnotate.passSwitch"]',
        body: 'ここ(赤枠)の縦並びボタンで Pass 1 / 2 / 3 を自由に切り替えられます。順番は固定ではなく、やりやすいところから入力できます。' },
      { title: 'Pass 1: ラリー区切り',
        body: '動画をタップして停止 → 「A 得点 / B 得点」の大ボタンをタップ。スコアとサーブ権は自動計算されます。' },
      { title: 'Pass 2: サーブと最終打',
        body: 'Pass 1 の各ラリーに「サーブ位置」「最終打の種類」を 4 ステップで追加します。これだけで EPV と勝率推定が動きます。' },
      { title: 'Pass 3: ストローク詳細',
        body: '各ラリーの全ストロークを詳細化。9-zone snap と指タッチ拡大鏡で coord 入力をサポートします。' },
      { title: 'オフラインで安全',
        body: '全入力は IndexedDB に保存され、接続復帰時に自動で送信されます。電波が切れても入力は失われません。' },
    ],
  },
  mobile_court_calibration: {
    id: 'mobile_court_calibration',
    title: 'モバイルでのコートキャリブ',
    steps: [
      { title: 'キャリブとは',
        body: 'コートの 4 隅+ネット 2 点を指でタップして、画像座標とコート実座標を対応付けます。CV 解析の精度はこれに依存します。' },
      { title: '指ルーペで正確に',
        body: 'タップ時、指の周辺が拡大鏡で表示されます。ライン交点に正確に合わせてください。' },
      { title: 'やり直しは何度でも',
        body: '保存後でも再度開いて修正できます。最後に保存した値が常に有効です。' },
    ],
  },
  desktop_annotator: {
    id: 'desktop_annotator',
    title: 'デスクトップ アノテーター',
    steps: [
      { title: 'ようこそ — 操作ガイド',
        body: 'この画面の主要な操作を順に紹介します。赤く光っている要素が今の説明対象です。「次へ」で進み、「スキップ」で今回だけ閉じ、「次回は表示しない」で以後出しません。' },
      { title: 'Mode タブで作業領域を切替',
        target: '[data-tutorial="annotator.modeTabs"]',
        body: 'ここ(赤枠)の Input / Review / Analysis / Settings タブで右パネルが切り替わります。入力時は Input、振り返り時は Review、分析は Analysis。' },
      { title: '動画プレイヤーで再生・停止・シーク',
        target: '[data-tutorial="annotator.videoPane"]',
        body: 'ここ(赤枠)が動画プレイヤーです。スペースキーで再生/停止、シークバーで頭出し、再生速度も変更できます。打球の瞬間で停止してから記録します。' },
      { title: '得点とラリー確定はスコアパネルで',
        target: '[data-tutorial="annotator.rallyPanel"]',
        body: 'ここ(赤枠)で現在のスコアを確認し、ラリー終了時に「得点者 × 終了種別」を選んで確定します。スコアとサーブ権は自動計算されます。' },
      { title: '打点ゾーン (9-zone) を入力',
        target: '[data-tutorial="annotator.hitZone"]',
        body: 'ここ(赤枠)で打点のコート位置 (9 分割ゾーン) を指定します。CV 候補があれば自動で埋まり、必要なら手動で上書きできます。' },
      { title: 'ショット種別パネルで打球を記録',
        target: '[data-tutorial="annotator.shotTypes"]',
        body: 'ここ(赤枠)のショット種別ボタンで、停止中の打球の種類を記録します。キーボードショートカットでも入力できます。' },
      { title: '直近ストロークは下端のヒストリーに',
        target: '[data-tutorial="annotator.historyStrip"]',
        body: 'ここ(赤枠)のヒストリーストリップから直前のストロークにクリックで seek できます。誤入力の修正が速いです。' },
      { title: 'Ctrl+K でコマンドパレット',
        body: 'どこからでも Ctrl+K (Mac: ⌘K) で機能検索。試合切替・選手検索・設定など全部ここから呼べます。' },
      { title: 'アノテーションの進め方',
        body: '基本の流れ: ①動画を再生して停止 → ②得点/ストロークを記録 → ③Review で確認 → ④Analysis で傾向を見る。迷ったら Ctrl+K で機能検索してください。' },
    ],
  },
  analysis_reading: {
    id: 'analysis_reading',
    title: '分析画面の読み方',
    steps: [
      { title: '分析タブで切り替え',
        target: '[data-tutorial="dashboard.topNav"]',
        body: 'ここ(赤枠)のタブで「概要 / 速報 / 振り返り / 成長 / 詳細分析」を切り替えます。横にスクロールすると残りのタブが出ます。ロールによって見えるタブは変わります。' },
      { title: '信頼度を必ず確認',
        body: '各分析結果には ConfidenceBadge (信頼度) と sample size 警告があります。サンプルが少ない場合は数値そのものより傾向だけを見てください。' },
      { title: 'EPV と勝率',
        body: 'Expected Point Value (EPV) はラリー終了時の期待得点価値です。勝率は試合全体ではなくその時点のスコア状況から推定されます。' },
      { title: '選手画面では伸びしろ表現',
        body: '選手用画面では「弱点」ではなく「伸びしろ」として表示されます。生の EPV や勝率は player ロールには出ません。' },
    ],
  },
  body_disclosure_toggle: {
    id: 'body_disclosure_toggle',
    title: '体組成データの開示先設定',
    steps: [
      { title: 'ここが開示設定です',
        target: '[data-tutorial="condition.disclosureToggle"]',
        body: 'ここ(赤枠)の「体組成データの開示設定」から、アナリスト / コーチへの開示を ON/OFF できます。default は同意 popup で選んだ値です。' },
      { title: 'いつでも撤回可',
        body: '開示を OFF にすると即時に反映され、当該ロールからは生の値が見えなくなります (3 段階の総合評価のみ見えます)。' },
      { title: '開示しない場合の影響',
        body: '開示しなくても本サービスのアノテーション機能は通常通り使えます。コーチング・解析の文脈で体組成相関が見られなくなるだけです。' },
    ],
  },
}

export type TutorialId = keyof typeof TUTORIALS
