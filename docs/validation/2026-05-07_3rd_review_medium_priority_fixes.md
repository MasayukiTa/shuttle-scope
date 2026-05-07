# 2026-05-07 3rd ローカル並列レビュー: 中優先 NOT FIXED 3 件 + 軽微 1 件の対応

`private_docs/2026-05-07_local_parallel_3rd_review_findings.md` で
NOT FIXED 5 件のうち、🟠 中優先 3 件 + 🟡 軽微 1 件 (camera operator
accept 順序、#2 と一緒に直す方が自然) を本コミットで対応。

残りの 🟡 NVML cross-process race は TODO 明記済で別ライン、
🟢 INFO 級項目は次サイクルで整理予定。

## 1. Electron `relaunch-app` の auth/origin gate (#1)

### 背景
2 ラウンド連続で未対応だった。`shuttlescope/electron/main.ts:707-720` は 30 秒
レートリミットだけで、renderer XSS から再起動 DoS を狙えば 30 秒に 1 回ずつ
撃てる状態だった。

### 変更
`shuttlescope/electron/main.ts:707-742` 付近の `ipcMain.handle('relaunch-app', ...)` を
3 段ガードに強化。

1. **origin gate**: `event.sender.id === mainWindow.webContents.id` を確認、かつ
   `event.senderFrame.parent == null` (top frame のみ)。videoWindow / 子 BrowserView /
   iframe 経由の relaunch を遮断。
2. **user-gesture gate**: `capture-webview-frame` と同じ 5 秒閾値で `_lastUserInputAt` を
   見る。renderer XSS では `before-input-event` を合成不能。
3. **rate limit**: 既存の 30 秒抑止は連発防止のため維持。

`mainWindow.webContents` に既に `before-input-event` リスナーは登録済 (1074 行) なので
追加 wiring は不要。

### 影響
- 通常の Electron UI 操作 (ユーザがメニューから "再起動" を選ぶ) は影響なし
  (直前の物理入力で `_lastUserInputAt` がフレッシュ)
- 自動テスト等で gesture なしに relaunch を呼ぶ経路があれば失敗 → そういう経路は
  本来禁止されているべき

## 2. WS カメラ operator session-owner check + accept 順序 (#2 / 軽微 #4)

### 背景
`backend/main.py:1730-1738` の JWT role-claim 検証 (admin/analyst/coach) は既に入って
いたが、**同一 role の他ユーザが他人のセッションを奪取できる** 問題が残っていた。
findings doc が指摘するのは「session-owner check が無い」点。
さらに軽微項目として `connect_operator` が `await ws.accept()` を slot check の **前** に
呼んでおり、`live.py` の cap-check-inside-lock + accept-on-success パターンと不揃い
だった。

### 変更
`shuttlescope/backend/ws/camera.py`:

1. `CameraSignalingManager.__init__` に `_operator_owners: dict[str, int]` を追加。
   session_code 単位で「最初に operator として接続した user_id」を記録。
2. `connect_operator(session_code, ws, user_id=None)` シグネチャ変更:
   - lock 内で slot check + owner check を完了してから `await ws.accept()`
     (#1a / #4 fix: live.py パターンに揃える)
   - 既存 owner と異なる user_id が来たら `close(4403, "operator owned by another user")`
   - 戻り値を `bool` に変更し、呼び出し側で False 時に return できるよう
3. `ws_camera_handler` (camera.py:207 以降):
   - operator 経路で JWT を再パースし `sub` から `user_id` を取り出して
     `connect_operator(..., user_id=...)` に渡す
   - loopback (`ALLOW_LOOPBACK_NO_AUTH=1`) で token が無いケースは
     `user_id=None` でオーナーチェック skip (緊急時のローカル復帰経路保護)
4. LOW finding: `relay_to_device` / `relay_to_viewer` の **送信失敗時の dict mutate** を
   `_slock` 経由に揃えた (新ロック規律に整合)

### owner 永続化方針
- `disconnect_operator` で operator slot は空けるが `_operator_owners` のエントリは残す。
  → 同じ user_id の再接続は通すが、別ユーザは奪えない
- `is_active=False` で SharedSession が終了するまで in-memory に保持。
  プロセス再起動で消えるが、その時はそもそも operator も再ハンドシェイクが必要

### 影響
- 通常の operator 1 名 (セッション作成者) ⇄ デバイス N + viewer M トポロジは挙動不変
- 別 analyst が同 session_code を知ってアクセスしても 4403 で弾かれる
- loopback 緩和経路 (Electron LAN モード) は user_id 不明でも従来通り operator になれる
- DB schema 変更 **なし** (production migration 不要)

## 3. `analysis_registry.check_or_raise` 新設 (#3)

### 背景
CLAUDE.md non-negotiable rule:
> "New analyses must declare evidence level, minimum sample size, and behavior
>  when the threshold is unmet."
> "Promotion ... is governed by promotion_rules.py (do not bypass)"

しかしレジストリには閾値が登録されているのみで、強制する関数が存在しなかった。
低 N の research/advanced 結果が ConfidenceBadge 任せで返っていた。

### 変更
`shuttlescope/backend/analysis/analysis_registry.py` に以下を追加:

1. `InsufficientSampleError` 例外 (FastAPI 非依存。HTTP 変換は routers 側で)
   - `to_dict()` で `{code: "insufficient_sample", analysis_type, tier, ...}` を返す
2. `evaluate_sample(analysis_type, sample_size) -> SampleDiagnostic` (非例外)
   - レスポンスに埋めるための診断データ
3. `check_or_raise(analysis_type, sample_size, *, enforce_tiers=("research", "advanced"))`
   - hard-gate 用。デフォルトで research / advanced を強制、stable は対象外
   - `enforce_tiers` で対象 tier を上書き可能 (テストや段階導入向け)
   - `sample_size` が None / 負値なら 0 として扱う defensive 実装

### 段階導入計画 (本 PR の範囲外)
ヘルパーはまず存在させ、テストで挙動を担保するに留める。tiered routers
全 6725 行への wiring は別 PR で段階的に行う。優先順:

1. **research tier** の単発エンドポイント (`opponent_policy`, `doubles_role`, `rs1` 系)
   - 期待動作: hard-gate (HTTP 422 / `code: insufficient_sample`)
2. **advanced tier** の集計エンドポイント
   - 期待動作: レスポンスに `sample_diagnostic` を含めるか hard-gate
3. **stable tier** は引き続き ConfidenceBadge 任せ (CLAUDE.md は強制を求めない)

routers 側の標準 wiring パターン (例):
```python
from backend.analysis.analysis_registry import check_or_raise, InsufficientSampleError

@router.get("/api/analysis/research/opponent-policy/{match_id}")
def get_opponent_policy(match_id: int, ...):
    n_rallies = _count_rallies(match_id, ...)
    try:
        check_or_raise("opponent_policy", n_rallies)
    except InsufficientSampleError as e:
        raise HTTPException(status_code=422, detail=e.to_dict())
    # ... 既存ロジック ...
```

### 影響
- 本 PR では既存の routers 挙動は **変更しない** (helper 追加のみ)
- 後続 PR で個別 endpoint を opt-in でガード化していく
- フロント側は `code: "insufficient_sample"` を catch して `ConfidenceBadge` の
  insufficient 状態にマップする実装が将来必要 (本 PR では未着手)

## テスト

### 追加した backend テスト
- `backend/tests/test_camera_operator_owner.py` (7 ケース)
  - accept 順序: 2 人目 operator は accept される前に close
  - owner 永続: disconnect 後も owner 保持
  - 別ユーザは再接続できない (4403)
  - 同じユーザは再接続できる
  - `user_id=None` (loopback) は owner check skip
  - 初回 user_id=None のセッションは別ユーザの参加を妨げない
- `backend/tests/test_analysis_registry_check.py` (12 ケース)
  - evaluate_sample: research / stable / unknown / 閾値ぴったり
  - check_or_raise: research raise / 閾値スキップ / advanced raise /
    stable はデフォルト免除 / enforce_tiers カスタム / 負値 / None / unknown

### 既存テスト確認
- `backend/tests/test_websocket_signaling.py` の `clear_camera_manager` fixture に
  `_operator_owners.clear()` を追加。既存 18 ケースは挙動不変

## 検証コマンド

```
cd shuttlescope
.\backend\.venv\Scripts\python -m pytest backend/tests/test_camera_operator_owner.py backend/tests/test_analysis_registry_check.py backend/tests/test_websocket_signaling.py -v
```

frontend は本 PR で変更ないが念のため:
```
cd shuttlescope
$env:NODE_OPTIONS="--max-old-space-size=16384"
npm run build
npx vitest run
```

## 残 NOT FIXED 一覧 (本 PR 後)

- 🟡 NVML cross-process race (TODO 明記済、severity NORMAL) — file-lock or DB advisory lock
- 🟢 INFO 級 6 件 — `before-input-event` リスナーマージ、mirror-broadcast per-type 検証、
  `_ytLive` regex コメント、`live.py` `_send_locks` の WeakKeyDictionary 化、
  `last_broadcast_at` セマンティクス、`relay_to_*` 既存ロック整合
  (relay_to_* は本 PR で部分対応)

## 本番影響評価

- DB schema 変更 **なし**
- 本番への SSH 操作 **なし**
- Electron 変更は LAN/Cloudflare 経由配備の renderer XSS 耐性向上のみ
- 認証/認可面の変更は backend 側のみで、Electron 内ローカル UX は不変
- analysis_registry の helper 追加はレジストリ挙動を変更しない
  (既存 endpoint はまだ helper を呼んでいないため)
