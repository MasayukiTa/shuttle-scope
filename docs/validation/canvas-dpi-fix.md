# Canvas DPI修正：別モニタ拡張時のオーバーレイ画質低下

## 変更日
2026-04-17

## 対象ファイル
- `shuttlescope/src/components/annotation/PlayerPositionOverlay.tsx`
- `shuttlescope/src/components/annotation/ShuttleTrackOverlay.tsx`

## 問題
高DPIモニタ（Windowsスケール125%/150%/200%など）に動画を別モニタ拡張表示した際、
YOLOプレイヤー検出BBoxおよびTrackNetシャトル軌跡のオーバーレイがぼやけて見えた。

### 根本原因
Canvas の `width`/`height` 属性をCSS論理ピクセル（`videoWidth`/`videoHeight`）で設定していたため、
ブラウザが物理ピクセルに拡大描画する際にアップスケーリングが発生していた。

```
例: devicePixelRatio = 1.5（150%スケール）の場合
修正前: canvas.width = 1920 → ブラウザが1.5倍に拡大 → ぼやける
修正後: canvas.width = 1920 * 1.5 = 2880 → 物理ピクセルと1:1対応 → シャープ
```

## 修正内容

各コンポーネントの `useEffect` 内で以下の変更を行った：

1. `canvas.width = videoWidth * dpr`（物理ピクセル解像度に設定）
2. `canvas.height = videoHeight * dpr`（同上）
3. `ctx.scale(dpr, dpr)`（コンテキストを論理ピクセル座標系に戻す）
4. 描画コードの `w`/`h` を `canvas.width`/`canvas.height` から `videoWidth`/`videoHeight` に変更
5. JSX canvas要素から `width`/`height` 属性を除去（`useEffect` 内で管理）

## 検証
- `npm run build` でビルドエラーなし
- 動画再生・オーバーレイ描画のロジックは変更なし
- DPR = 1.0（非高DPI）環境では動作変化なし（1.0倍スケールは従来と等価）
