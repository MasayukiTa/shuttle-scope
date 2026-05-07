# player ロール: team_id / role の silent drop を明示拒否化

実施日: 2026-05-08
発見ラウンド: round180 P6

## 背景

PUT `/api/auth/users/{target_id}` の player ロール処理 (`backend/routers/auth.py:1432-1442`) は、player が自身を編集する場合に `username / team_name / player_id` のいずれかが body に含まれていれば 403 で明示拒否し、それ以外は `display_name / password / pin` のみで body を再構築して silent drop を回避する設計だった。

> player が権限関連フィールドを送ってきたら silent drop ではなく 403 で明示拒否する (silent success は攻撃検出を困難にする)

ところが reject 対象リストから `team_id` (および `role`) が漏れていた。

## Finding (round180 P6)

| ケース | Before | 実害 |
|---|---|---|
| player 自身に `{"team_id": 1}` PUT | 200 success (silent drop) | team_id 自体は変わらない (UserUpdate 再構築で除外) が、攻撃者には「成功」と見える |
| player 自身に `{"role": "admin"}` PUT | 403 ✅ (admin-only check で reject) | 別経路で防御済 |
| player 自身に `{"player_id": 1}` PUT | 403 ✅ | OK |
| player 自身に `{"team_name": "..."}` PUT | 403 ✅ | OK |
| player 自身に `{"username": "..."}` PUT | 403 ✅ | OK |

実害自体はないが (silent drop で実際の値変更なし)、ポリシーは "明示拒否" を宣言しているのに `team_id` だけ silent success になっており、policy と挙動が矛盾。攻撃者からは team 移動が成功したように見え、後続で「自分は team 1 所属」と思い込んで他経路を試す可能性。

## 修正

`backend/routers/auth.py:1437` の reject リストに `body.team_id` と `body.role` を追加。

```python
# Before
if any(v is not None for v in (body.username, body.team_name, body.player_id)):

# After (round180 P6 fix)
if any(v is not None for v in (
    body.username, body.team_name, body.team_id,
    body.player_id, body.role,
)):
```

`role` は前段の admin-only check (line 1363) で既に 403 になるが、防御深化として player 経路でも明記する。エラーメッセージも `username / team / role / player_id` に更新。

## 検証

修正後 deploy → round180 P6 を再実行して以下が 403 になることを確認:
- `self_team_change` (`{"team_id": 1}`) → 403 「player ロールは team を変更できません」
- `self_role_escalate` (`{"role": "admin"}`) → 403 (admin-only check で先行 reject)
- `self_player_id_change` (`{"player_id": 1}`) → 403

許可される操作:
- `{"display_name": "..."}` → 200
- `{"password": "..."}` → 200
- `{"pin": "..."}` → 200
