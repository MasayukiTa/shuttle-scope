# auth: login enumeration oracle fix (lockout body / status normalization)

- 検出: 2026-05-24 攻撃 round 280
- 修正対象: `shuttlescope/backend/routers/auth.py`

## 問題

`/api/auth/login` の応答が 4 状態で外部から区別可能だった:

| 状態 | 旧応答 |
|---|---|
| 非存在 user | 401 `{"detail":"login failed"}` |
| 在 user + wrong pw (< MAX) | 401 `{"detail":"login failed"}` |
| 在 user + wrong pw == MAX (lock 確定) | **429 `{"detail":"ログイン失敗が3回に達しました。30分間ロックされます。"}`** |
| 在 user + locked 状態の追加試行 | **429 `{"detail":"アカウントがロックされています。約N分後に再試行してください。"}`** |

攻撃手順 (R280-E で実証):
- 任意 username に対し wrong password で 3 回投げる
- 3 回目以降の応答が 429 → 実在 user 確定
- 401 のままなら非存在 user

非存在 user 経路と Body 内容 + status code が完全に分かれていたため、
時間オラクル防御 (`_timing_padding_db_write` / dummy bcrypt) を補完しても
**コンテンツオラクルで username enumeration が成立**。

## 修正内容

`backend/routers/auth.py`

1. `_check_lockout()`: 旧 `429 + "アカウントがロックされています…"` →
   **`401 + "login failed"`** に変更 (非存在 user の応答と同一)
2. `_on_login_failure()` の MAX 到達分岐: 旧 `429 + "ログイン失敗が…"` →
   **`401 + "login failed"`** に変更

これで login 失敗の 4 状態すべて `401 + "login failed"` に統一され、
外部からは状態判定不可能になる。

`account_locked` event は内部 audit log には引き続き記録されるため、
admin / 運用側はロック発生を把握できる。

## UX への影響

- 正規 user がパスワードを忘れて 3 回ミスして lockout になった場合、
  4 回目以降の応答が「password 間違い」と同じ 401 になる。
- 「自分のアカウントがロックされた」ことを login 画面から判定できない。
- 対策: ロックされた user は admin に問い合わせて状態確認 + 解除する運用
  (password reset 機能は別途無効化中)。
- これは password reset endpoint (`SS_PASSWORD_RESET_ENABLED=0` で 503)
  と同じ「enumeration 防御優先 + UX 譲歩」のポリシーに揃える形。

## verify 手順 (deploy 後)

```python
# 非存在 user
POST /api/auth/login {"grant_type":"password","username":"ZZZNONEXIST","password":"x"}
# admin に対し 3 連続 wrong pw (lockout 発動させる + 4 回目で旧 429 に当たる経路)
for _ in range(4):
    POST /api/auth/login {"grant_type":"password","username":"adminTakeuchi_","password":"wrong"}
```

期待: 全て **`401 {"detail":"login failed"}`** で body / status とも同一。

verify 後は admin lockout を DB 直 UPDATE で解除:
```sql
UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username='adminTakeuchi_';
```

## 副作用検討

- 公開 enum oracle は閉じる
- account_locked audit log は維持 → admin 監視ダッシュボードで把握可能
- 既存 test は lockout の特定 body / status を assert していないため破壊なし
- bot 攻撃の brute-force 防御は failed_attempts カウンタ + per-user lockout
  自体の動作で引き続き機能 (応答が 401 で偽装されても、ロック中は password
  正しくても認証通らないため)
