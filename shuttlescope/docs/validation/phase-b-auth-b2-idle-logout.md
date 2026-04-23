# Phase B-2: 無操作 15 分で自動ログアウト (A4)

Date: 2026-04-23

## 目的
Refresh token による透過再発行だけでは、ブラウザ/Electron を開いたままの放置でも
ログイン状態が維持されてしまう。renderer 側で操作を監視し、15 分無操作で
`authLogout()` + `clearRole()` を実行する。

- 試合観戦 (2h 超) などアクティブ操作がある場合は発火しない。
- 画面を閉じずに席を離れた場合 15 分で強制ログアウト → 次のアクセスで LoginPage。

## 変更

### src/hooks/useIdleLogout.ts (新規)
- `mousedown / keydown / touchstart / pointerdown / wheel / visibilitychange` を監視。
- `lastActivityRef` をイベントで更新し、30 秒毎に閾値超過を判定。
- `enabled=false` 時 (= ログアウト済み) はリスナーを張らない。
- `onIdle` は ref 経由で最新値を参照するため再バインド不要。

### src/App.tsx
- `ProtectedMainRoute` に `useIdleLogout({ enabled: !!token, timeoutMs: 15min, onIdle })` を追加。
- `onIdle` は `authLogout()` (失敗は無視) → `clearRole()` の順。

## 検証
- `npm run build` 成功 (9.96s)。
- 既存の login/logout/refresh フローへの追加のみで、既存テストには影響なし。

## 既知の制約
- タイマーは renderer プロセス単位。複数ウィンドウ開いている場合は各ウィンドウで独立に判定する
  (現状 Electron 単一ウィンドウのため問題なし)。
- `visibilitychange` をアクティビティ扱いにしているため、ウィンドウ復帰時はリセットされる。
  これは意図通り (復帰直後の即ログアウトを避ける)。

## 今後
- B-3: password reset flow。
- B-4: 連続失敗ログインのレート制限。
