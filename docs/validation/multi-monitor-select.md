# マルチモニタ選択UI追加

## 変更日
2026-04-17

## 対象ファイル
- `shuttlescope/src/pages/AnnotatorPage.tsx`
- `shuttlescope/src/i18n/ja.json`

## 変更内容

### 背景
「別モニタで動画表示」は従来、非プライマリモニタの先頭を自動選択していた。
デスクトップPCなど3台以上のモニタ構成では表示先を選べなかった。

### 変更内容

1. **`selectedDisplayId` state 追加**（AnnotatorPage.tsx）
   - 初期値: `getDisplays()` 取得時に非プライマリの最初のモニタIDをセット
   - 未設定時のフォールバックあり（従来挙動を維持）

2. **`handleOpenVideoWindow` 修正**（AnnotatorPage.tsx）
   - `displays.find(d => !d.isPrimary)` の自動選択を廃止
   - `selectedDisplayId` を使用して指定モニタに開く

3. **モニタ選択 `<select>` 追加**（AnnotatorPage.tsx）
   - 表示条件: 非プライマリモニタが **2台以上** のときのみ表示
   - 1台のとき（ノートPC+外部1枚）: UIに変化なし、従来と同じ動作
   - ラベルは Electron `screen.getAllDisplays()` が返す解像度文字列（例: `1920×1080`）

4. **i18n キー追加**（ja.json）
   - `dual_monitor.select_display`: "表示先モニタを選択"

## 動作仕様

| 非プライマリモニタ数 | UI |
|---|---|
| 0台 | ボタン非表示（従来通り） |
| 1台 | ボタンのみ（選択UI非表示、従来通り） |
| 2台以上 | `<select>` + ボタン |

## 検証
- `npm run build` でビルドエラーなし
- 1台構成では動作変化なし
