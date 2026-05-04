# Video Token Leak Runbook

UUID 形式の video_token (app://video/{token}) が漏洩した場合の対応。

## シナリオ別対応

### A. 単一 video_token の漏洩

UI から再発行ボタン使用:
1. 試合一覧から該当試合の編集モードを開く
2. 「🔄 動画リンクを再発行」をクリック
3. 確認 → 即座に新 token に置換、旧 token は次回アクセスで 404

### B. 複数 video_token の漏洩 (10 件以上)

API で個別に再発行 (curl):
```bash
for MATCH_ID in 1 2 3 ...; do
  curl -X POST -H "Authorization: Bearer <admin_token>" \
       -H "X-Idempotency-Key: $(uuidgen)" \
       https://app.shuttle-scope.com/api/matches/${MATCH_ID}/reissue_video_token
done
```

### C. 全 video_token の漏洩 (鍵漏洩等で全件失効が必要)

緊急エンドポイント (Phase C2 で実装):
```bash
curl -X POST -H "Authorization: Bearer <admin_token>" \
  https://app.shuttle-scope.com/api/admin/security/reissue_all_video_tokens
```

このエンドポイントは:
- 全 Match の video_token を新 UUID4 に置換
- access_log に `emergency_reissue_all_video_tokens` を記録
- 完了後の所要時間と処理件数を返す

実行後、全ユーザーが映像再生不可になる → 試合一覧を再ロードすれば新 token で再生再開。

## 影響評価

video_token 漏洩 ≠ データ漏洩。
理由: token を知っていてもログインしていなければ 401、
ログインしていても所有チーム外なら 404 (`user_can_access_match` チェック)。

ただし以下のケースで実害あり:
- 同チーム内に内部不正者がいて token を取得 → 動画視聴可能
- 漏洩した token + 漏洩した有効 JWT の組み合わせ
- video_url (YouTube 公開 URL) は元から公開情報のため別問題
