# フロント側 セキュリティ規約 (Phase 1 / Phase A 連動)

このドキュメントは、新規コード追加時に守るべきセキュリティ規約をまとめる。

## 1. 動画 URL の構築

### ✅ DO

```tsx
import { getVideoSrc } from '@/utils/videoSrc'

const src = getVideoSrc(match)  // app://video/{token} または video_url
```

### ❌ DON'T

```tsx
// 1. 生のローカルパスを直接 video src に渡さない
<video src={`localfile:///${rawPath}`} />

// 2. video_local_path をフロントから読まない
const path = match.video_local_path  // ← Phase 1 以降、API レスポンスに含まれない

// 3. パスを含む文字列を表示しない (ファイル名のみは OK)
<div>{match.video_local_path}</div>  // ← パス丸見え
<div>📁 {match.video_filename}</div>  // ✅ ファイル名のみ
```

## 2. 重要操作の冪等性

副作用のある操作 (削除、再発行、export) は必ず X-Idempotency-Key を付ける。

### ✅ DO

```tsx
import { apiPost, apiDelete, newIdempotencyKey } from '@/api/client'

// 削除
await apiDelete(`/matches/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() })

// 再発行
await apiPost('/matches/123/reissue_video_token', {},
              { 'X-Idempotency-Key': newIdempotencyKey() })
```

### ❌ DON'T

```tsx
// 二度押しで二重実行されるリスクあり
await apiPost('/matches/123/reissue_video_token', {})
```

## 3. 機密情報のログ出力

`console.log` / 通知メッセージに以下を含めない:

- video_local_path 全パス（ファイル名のみは OK）
- video_token 全長（プレフィックス 8 文字程度なら OK）
- JWT
- パスワード / PIN
- SS_OPERATOR_TOKEN

## 4. ファイル選択

### ✅ DO

```tsx
// ユーザーが明示的に選択（ダイアログ経由）
const url = await window.shuttlescope.openVideoFile()
```

### ❌ DON'T

```tsx
// 任意パスを指定
const url = `localfile:///C:/path/to/video.mp4`
// ← Electron 側 path_jail でブロックされる
```

## 5. apiPost / apiDelete の extraHeaders

第 3 引数で追加ヘッダを渡せる。X-Idempotency-Key 以外でも、デバッグ用ヘッダを付ける時に使う。

```tsx
// 例: トレースヘッダ
await apiPost('/some/endpoint', body, {
  'X-Idempotency-Key': newIdempotencyKey(),
  'X-Request-Trace-Id': traceId,
})
```

## 6. 共有リンクの扱い

video_token 経由の URL (`app://video/{token}`) は **認証必須**だが、第三者へ共有する用途ではない。
共有が必要な場合は LAN セッション機能を使うこと。

漏洩した場合は試合編集画面の「🔄 動画リンクを再発行」で即座に無効化できる。

## 7. 削除の確認ダイアログ

破壊的操作の前は必ず `window.confirm` または専用モーダルで確認を取る。

```tsx
if (!window.confirm(t('match.list.delete_confirm'))) return
await apiDelete(`/matches/${id}`, { 'X-Idempotency-Key': newIdempotencyKey() })
```

## 違反検知

CI で以下を grep で検知することを推奨:

- `localfile:///` 直接埋め込み (`getVideoSrc` 経由ならOK)
- `video_local_path` の読み取り (型定義以外)
- `apiDelete\(` で X-Idempotency-Key なし
