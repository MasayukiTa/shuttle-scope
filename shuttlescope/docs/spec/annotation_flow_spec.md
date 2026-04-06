# アノテーション入力フロー 仕様書

> 作成: 2026-04-06  
> 対象: `AnnotatorPage`, `useKeyboard`, `annotationStore`, `CourtDiagram`

---

## 1. 状態マシン（State Machine）

```
┌─────────────────────────────────────────────────────────────────┐
│  isRallyActive=false / inputStep='idle'                         │
│  【ラリー待機】                                                    │
│  表示: ラリー開始ボタン / 見逃しラリーボタン / ShotTypePanel(薄暗)  │
└──────┬───────────────────────────────────────────────────────────┘
       │ ショットキー押下 or ラリー開始ボタン
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  isRallyActive=true / inputStep='idle'                          │
│  【ラリー中・ショット待ち】                                         │
│  表示: ShotTypePanel / AttributePanel / StrokeHistory / undo    │
└──────┬──────────────────────────────────────────────────────────┘
       │ ショットキー押下 or ShotTypePanel クリック
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  isRallyActive=true / inputStep='land_zone'                     │
│  【落点入力待ち】                                                   │
│  表示: CourtDiagram(OOB+NET付き) / スキップボタン / AttributePanel│
│  ※ ShotTypePanel は非表示（落点入力中は混乱を避ける）              │
└──────┬────────────────┬────────────────┬────────────────────────┘
       │ Zone9選択       │ OOB/NET選択     │ Skip(0キー)
       ▼                ▼                ▼
   idle(active)    rally_end         idle(active)
       │
       │ Enter(1ストローク以上) or OOB/NET選択
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  isRallyActive=true / inputStep='rally_end'                     │
│  【ラリー終了確認】                                                 │
│  表示: 勝者ボタン×2 / エンドタイプボタン×6 / キャンセル             │
│  ※ ShotTypePanel・CourtDiagram・AttributePanel は非表示           │
└──────┬──────────────────────────────────────────────────────────┘
       │ 勝者+エンドタイプ選択（通常モード）/ エンドタイプ→勝者（MDモード）
       ▼
   idle(false) ← ラリー確定・DB保存
```

---

## 2. 各状態で表示すべき UI 要素

| 要素 | idle(false) | idle(true) | land_zone | rally_end |
|------|-------------|------------|-----------|-----------|
| **ShotTypePanel** | △表示（ショット待ち示唆。disabled でない） | ✓ | ✗ 非表示 | ✗ 非表示 |
| **CourtDiagram** | ✗ | ✗ | ✓（OOB+NET付き） | ✗ |
| **AttributePanel** | ✗ | ✓ | ✓ | ✗ |
| **StrokeHistory** | ✓ | ✓ | ✓ | ✓ |
| **ラリー開始ボタン** | ✓ | ✗ | ✗ | ✗ |
| **見逃しラリーボタン** | ✓ | ✗ | ✗ | ✗ |
| **落点スキップボタン** | ✗ | ✗ | ✓ | ✗ |
| **ラリー終了パネル** | ✗ | ✗ | ✗ | ✓ |
| **Undoボタン** | ✗ | ✓（0ストローク時disabled） | ✓ | ✗ |
| **Enter→終了ボタン** | ✗ | ✓（1ストローク以上） | ✓（1ストローク以上） | ✗ |

> **現状の問題点**:
> - `land_zone` 中も ShotTypePanel が表示されている → 混乱の原因。非表示が正しい。
> - `idle(false)` で ShotTypePanel が完全に非表示 → キーガイドが見えない。

---

## 3. キーボードショートカット（状態別）

### 3.1 常時有効

| キー | 動作 |
|------|------|
| `Space` | 動画 再生/一時停止 |
| `←` | 1フレーム戻し（1/30秒） |
| `→` | 1フレーム送り |
| `Shift+←` | 10秒戻し |
| `Shift+→` | 10秒送り |
| `Tab` | プレイヤー切替（A↔B） |

> ⚠️ INPUT/TEXTAREA にフォーカス中はショートカット全無効

### 3.2 `idle` または `land_zone`（ラリー中）

| キー | 動作 |
|------|------|
| `Numpad/` | バックハンドトグル |
| `Numpad*` | ラウンドヘッドトグル |
| `Numpad-` | ネット上下サイクル（未→上→下→未） |
| `Ctrl+Z` | 直前ストロークアンドゥ |

### 3.3 `idle` のみ（ラリー中・未開始問わず）

| キー | 動作 | 備考 |
|------|------|------|
| `n` | ネットショット | |
| `c` | クリア | |
| `p` | プッシュ/ラッシュ | |
| `s` | スマッシュ | |
| `d` | ディフェンシブ | |
| `v` | ドライブ | |
| `l` | ロブ | |
| `o` | ドロップ | |
| `x` | クロスネット | |
| `z` | スライス | **※ Ctrl+Z（undo）と混同注意** |
| `a` | アラウンドヘッド | |
| `f` | フリック | |
| `h` | ハーフスマッシュ | |
| `b` | ブロック | |
| `0` | その他 | **※ テンキー0はスキップ（別処理）** |
| `1` | ショートサービス | **※ 通常数字キーのみ（Numpad1は落点）** |
| `2` | ロングサービス | |
| ※ | → 直前に idle(false) なら自動ラリー開始 | |

> **⚠️ 現状の問題点**:
> - `land_zone` 中もショットキーが有効 → 落点入力中に誤爆でショット種別が書き換わる
> - **修正方針**: `land_zone` 状態ではショットキーを無効化する

### 3.4 `land_zone` のみ

| キー | 動作 |
|------|------|
| `Numpad1` | NL（ネット左） |
| `Numpad2` | NC（ネット中） |
| `Numpad3` | NR（ネット右） |
| `Numpad4` | ML（ミドル左） |
| `Numpad5` | MC（ミドル中） |
| `Numpad6` | MR（ミドル右） |
| `Numpad7` | BL（バック左） |
| `Numpad8` | BC（バック中） |
| `Numpad9` | BR（バック右） |
| `Numpad0` / `.` / `NumpadEnter` | 落点スキップ（land_zoneなしで確定） |
| `Escape` | キャンセル（idle に戻る・pendingStroke クリア） |

> **⚠️ テンキー配列とコート対応（物理キーとコートが一致）**
> ```
> [7:BL] [8:BC] [9:BR]   ← バック（遠い）
> [4:ML] [5:MC] [6:MR]   ← ミドル
> [1:NL] [2:NC] [3:NR]   ← ネット前（近い）
> ```

> **⚠️ OOB/NETゾーンはテンキーでは選択不可（クリックのみ）**  
> → 将来的に `Numpad+` でOOB入力補助を検討

### 3.5 `rally_end` のみ

| キー | 動作 |
|------|------|
| `1` | エンドタイプ: ace |
| `2` | エンドタイプ: forced_error |
| `3` | エンドタイプ: unforced_error |
| `4` | エンドタイプ: net |
| `5` | エンドタイプ: out |
| `6` | エンドタイプ: cant_reach |
| `Escape` | ラリー終了キャンセル（idle に戻る） |

> ⚠️ 通常モードでは 1-6キー → エンドタイプ選択後は**別途クリックで勝者確定**が必要。  
> **MDモードのみ** エンドタイプ → 勝者ボタンの2ステップ。

---

## 4. コートダイアグラム仕様

### 4.1 `mode` の決定ルール

```
currentPlayer === 'player_a' → mode='land'（相手コート＝上半分がアクティブ）
currentPlayer === 'player_b' → mode='hit'（自コート＝下半分がアクティブ）
```

> バドミントンのラリーポイント制：打った選手の「相手側」に落ちる

### 4.2 ゾーン一覧

**コート内 9マス（Zone9）**

```
上半分（mode='land'でアクティブ、mode='hit'で薄暗）:
  BL BC BR  ← バックライン側
  ML MC MR
  NL NC NR  ← ネット側
下半分（mode='hit'でアクティブ）: 上下反転で NL が上
```

**コート外 OOBゾーン（ZoneOOB）- 赤破線**

```
mode='land' (相手コート側):
  OB_BL OB_BC OB_BR  ← バック外（上）
  OB_LL OB_LM OB_LN  ← 左サイド外
  OB_RL OB_RM OB_RN  ← 右サイド外
  OB_FL OB_FR        ← ネット前ショート（黄色）

mode='hit' (自コート側): 上下ミラー
```

**ネット接触ゾーン（ZoneNet）- オレンジ**

```
NET_L  NET_C  NET_R  ← ネットライン（y=193-207）上に配置
                        NL/NC/NR の列に対応
```

> **⚠️ 現状の問題点**: NET_L/NC/NR の SVG 描画順序が OWN_ZONES より前のため、
> OWN_ZONES NL/NC/NR（y=200-266）に覆われ、y=200-207 エリアがクリック不可。
> → **修正済み**: NET zone を OWN_ZONES の後（最後）に描画する

### 4.3 ゾーン選択後の動作

| ゾーン種別 | 選択後の状態 |
|-----------|------------|
| Zone9（コート内）| `idle(active)`（ラリー継続） |
| ZoneOOB（コート外）| `rally_end`（アウト確定・即終了確認） |
| ZoneNet（ネット接触）| `rally_end`（ネット確定・即終了確認） |

### 4.4 autoHitZone（打点自動推定）

前ストロークの `land_zone` を今ストロークの `hit_zone` として自動設定。

- 前 `land_zone` が Zone9 → そのまま hit_zone に使用
- 前 `land_zone` が OOB（`OB_`始まり）→ 使用しない（undefined）
- 前 `land_zone` が NET（`NET_`始まり）→ 使用しない（undefined）

---

## 5. ラリー終了（rally_end）フロー

### 5.1 通常モード

```
[A得点] 列                   [B得点] 列
  ace           (1)            ace           (1)
  forced_error  (2)            forced_error  (2)
  unforced_error(3)            unforced_error(3)
  net           (4)            net           (4)
  out           (5)            out           (5)
  cant_reach    (6)            cant_reach    (6)

クリックで即確定（勝者＋エンドタイプを同時に選択）
1-6キー選択: 最後に押した側（A/B）のキー（未実装 → 要検討）
```

> **⚠️ 通常モードのキー問題**:
> 1-6キーは「エンドタイプ選択」だが、どの勝者か未指定のまま。  
> 現状はキーでエンドタイプをハイライトするだけで、勝者ボタンを押す必要がある。  
> MDモードとの一貫性が取れていない。  
> **修正方針**: 通常モードでは `1-6` キーを使わず、常にクリックで選択する。  
> MDモードでのみ `1-6`→エンドタイプ → `A/B`ボタン の2ステップとする。

### 5.2 MDモード（Match Day Mode）

```
Step1: エンドタイプ選択（クリックまたは1-6キー）
  [ace][forced_error][unforced_error][net][out][cant_reach]
  ↑ 選択すると黄色ハイライト

Step2: 勝者ボタン確定（エンドタイプ選択後に有効化）
  [A得点（青）]   [B得点（橙）]
```

### 5.3 OOB/NET選択後の自動 rally_end

- OOB ゾーン選択 → ストローク確定（land_zone=OB_*） → `rally_end`
- NET ゾーン選択 → ストローク確定（land_zone=NET_*） → `rally_end`
- エンドタイプの事前プリセット（検討）:
  - OB_BL/BC/BR/LL/LM/LN/RL/RM/RN → `out`
  - OB_FL/FR → `net`（ショートサービス前に落ちた = ネット手前落下）
  - NET_* → `net`

---

## 6. アンドゥ仕様

| 状態 | 動作 |
|------|------|
| `idle(true)` で Ctrl+Z | 直前ストロークを削除。プレイヤーを1つ前に戻す。pendingStroke クリア |
| `land_zone` で Ctrl+Z | 現在の pendingStroke をクリアして `idle` に戻す（ストローク未確定なので削除対象なし） |
| ストロークが0件の場合 | 何もしない |

> **⚠️ 現状の問題点**: `land_zone` 中に Ctrl+Z を押すと `undoLastStroke()` が呼ばれ、
> 1つ前に確定したストロークが消えてしまう。意図は「今の pending をキャンセルしたい」はず。  
> **修正方針**: `land_zone` の Ctrl+Z は pending クリア（idle に戻す）のみ。確定済みストロークは消さない。

---

## 7. 自動保存（Auto-save）仕様

### 7.1 保存タイミング

- 各ストローク確定（`selectLandZone` / `skipLandZone`）のたびに localStorage へ書き込み
- `confirmRally` 成功後: 削除
- `resetRally` 後: 削除
- ページ離脱前: そのまま残す（復元用）

### 7.2 保存キー

```
shuttlescope.autosave.{matchId}
```

### 7.3 保存データ

```json
{
  "setId": 123,
  "rallyNum": 5,
  "strokes": [...],
  "savedAt": 1712345678000
}
```

### 7.4 復元フロー

1. AnnotatorPage 初期化完了後、localStorage を確認
2. データが存在し、現在の `setId` と `rallyNum` が一致 → 復元確認ダイアログ
3. 復元: `store` に strokes を読み込む
4. 復元しない: 削除

---

## 8. 既知バグと修正状況

| # | 問題 | 原因 | 状態 |
|---|------|------|------|
| 1 | NET_L/C/R がクリックできない | SVG描画順：OWN_ZONES NL/NC/NR が NET ゾーン上に重なる | **修正済み** |
| 2 | `land_zone` 中にショットキーが効く | `inputStep === 'idle' \|\| inputStep === 'land_zone'` の条件が広すぎる | 修正予定 |
| 3 | Escape in `land_zone` で pendingStroke が残る | `cancelRallyEnd()` が inputStep='idle' にするだけ | 修正予定 |
| 4 | ShotTypePanel が idle(false) で非表示 | `isRallyActive` 条件でガードしている | 修正予定 |
| 5 | `land_zone` 中も ShotTypePanel が表示される | `inputStep !== 'rally_end'` の条件が甘い | 修正予定 |
| 6 | 総合成長判定が誤って「保留」 | `window` 算出に `match_count`（未アノテ含む全試合）を使用、アノテ済み件数ベースにすべき | **修正済み** |
| 7 | 遷移マトリクス 上位遷移の数値が右端に流れる | `ml-auto` が count と % を片側に寄せすぎ | **修正済み** |
| 8 | アノテーション一時保存がない | 未実装 | **実装済み** |
| 9 | 動画未設定時に左パネルが消えファイルピッカーが使えない | `videoSourceMode === 'none'` で非表示 | **修正済み** |

---

## 9. ショットタイプキー一覧（ShotTypePanel 対応）

| キー | ショット | 表示コンテキスト |
|------|---------|----------------|
| `1` | short_service | サービスのみ |
| `2` | long_service | サービスのみ |
| `n` | net_shot | サービス以外 |
| `c` | clear | after_net以外 |
| `p` | push_rush | サービス以外 |
| `s` | smash | サービス以外 |
| `d` | defensive | サービス以外 |
| `v` | drive | サービス以外 |
| `l` | lob | サービス以外 |
| `o` | drop | サービス以外 |
| `x` | cross_net | サービス以外 |
| `z` | slice | after_net以外 |
| `a` | around_head | after_net以外 |
| `f` | flick | サービス以外 |
| `h` | half_smash | サービス以外 |
| `b` | block | サービス以外 |
| `0` | other | 全コンテキスト |

---

## 10. 実装優先度

| 優先度 | タスク |
|--------|--------|
| **P0（即修正）** | NET ゾーンクリック不可 |
| **P0（即修正）** | 成長判定の誤ったpending表示 |
| **P0（即修正）** | 遷移マトリクスレイアウト崩れ |
| **P1（次フェーズ）** | `land_zone` 中ショットキー無効化 |
| **P1（次フェーズ）** | Escape in `land_zone` で pendingStroke クリア |
| **P1（次フェーズ）** | ShotTypePanel を全状態で正しく表示制御 |
| **P2（将来）** | OOB/NET選択後のエンドタイプ事前プリセット |
| **P2（将来）** | `land_zone` Ctrl+Z の pending キャンセル分離 |
