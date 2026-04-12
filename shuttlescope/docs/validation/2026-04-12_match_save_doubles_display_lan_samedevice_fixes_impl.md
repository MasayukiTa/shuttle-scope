# 試合保存バグ / ダブルス表示 / LAN同一デバイスアクセス修正
**Date:** 2026-04-12

---

## 1. 試合保存 422 エラー修正（Pydantic v2.12.5 フィールド名衝突）

### 変更ファイル
- `backend/routers/matches.py`

### 原因
Pydantic v2.12.5 において、フィールド名 `date` と型アノテーション `date`（`from datetime import date`）が同名になり、型が `NoneType` に解決される。`none_required` バリデーションエラーが発生し、PUT /api/matches/{id} が常に 422 を返す。

### 修正
```python
# Before
from datetime import date

class MatchCreate(BaseModel):
    date: date

class MatchUpdate(BaseModel):
    date: Optional[date] = None

# After
from datetime import date as _date

class MatchCreate(BaseModel):
    date: _date

class MatchUpdate(BaseModel):
    date: Optional[_date] = None

today = _date.today()  # quick_start_match 内も同様
```

---

## 2. 試合編集フォーム player_b / partner_b 選択が保存に反映されない問題

### 変更ファイル
- `src/pages/MatchListPage.tsx`

### 原因
`PlayerSearchSelect` に渡す `setQuery` prop に副作用 `setForm(f => ({ ...f, player_b_id: '' }))` を含めていた。React 18 のバッチ更新により、`setValue(id)` の後に ID が空文字にリセットされていた。

### 修正
```tsx
// Before
setQuery={(q) => { setPlayerBQuery(q); setForm((f) => ({ ...f, player_b_id: '' })) }}

// After
setQuery={setPlayerBQuery}
```
`partner_b` も同様。

---

## 3. LAN ブラウザアクセス時 React が起動しない問題（MIME タイプ）

### 変更ファイル
- `backend/main.py`

### 原因
Windows では `.js` の MIME タイプがレジストリ未登録の場合があり、Starlette `StaticFiles` が `application/octet-stream` で配信 → ブラウザが `type="module"` スクリプトを拒否 → React マウント失敗。

### 修正
```python
import mimetypes
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/javascript', '.mjs')
mimetypes.add_type('text/css', '.css')
```
モジュールロード時（FastAPI app 生成前）に実行。

---

## 4. ダブルス時のスコアエリアに両選手名表示

### 変更ファイル
- `src/pages/AnnotatorPage.tsx`

### 実装内容
モバイル sticky ヘッダーおよびデスクトップスコアパネルのスコア表示部分に対して、シングルス/ダブルス判定を追加。

```tsx
{match?.format !== 'singles' ? (
  <div className="flex flex-wrap justify-center gap-x-1 text-[10px] text-gray-400 max-w-[110px]">
    <span className="whitespace-nowrap">{match?.player_a?.name ?? 'A'}</span>
    <span className="opacity-40">/</span>
    <span className="whitespace-nowrap">{match?.partner_a?.name ?? '—'}</span>
  </div>
) : (
  <div className="text-xs text-gray-400 truncate">{match?.player_a?.name ?? 'A'}</div>
)}
```
- `flex-wrap` により幅が狭い場合は上下2行に折り返す
- player_b 側も同様

---

## 5. ダブルス打者パネル：ホバーでチーム名表示 / 数字キーヒント

### 変更ファイル
- `src/pages/AnnotatorPage.tsx`

### 実装内容
打者選択ボタンに `title` 属性とキー番号表示を追加。

```tsx
<button
  onClick={() => store.setHitter('player_a')}
  className={btnCls('player_a')}
  title={[match.player_a?.team, '[7]'].filter(Boolean).join(' ')}
>
  <span className="opacity-40 text-[9px] mr-0.5">7</span>{nameA}
</button>
// 8=partner_a, 9=partner_b, 0=player_b も同様
```
- `title`: チーム名（未設定時は省略）+ キーヒント `[7]`
- ボタン左端に薄い数字（9px）を表示

---

## 6. ダブルス打者キーボードショートカット 7/8/9/0

### 変更ファイル
- `src/hooks/useKeyboard.ts`

### 実装内容
`UseKeyboardOptions` に `onHitterSelect` を追加し、`idle(true)` セクションに処理を追加。

```typescript
const HITTER_KEYS: Record<string, 'player_a' | 'partner_a' | 'partner_b' | 'player_b'> = {
  '7': 'player_a', '8': 'partner_a', '9': 'partner_b', '0': 'player_b',
}

// idle(true) 内、Tab キー処理の直後
if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && !e.code.startsWith('Numpad')) {
  const hitter = HITTER_KEYS[e.key]
  if (hitter) {
    e.preventDefault()
    onHitterSelect?.(hitter)
    return
  }
}
```

- Numpad 数字キーは除外（テンキーでの誤発動防止）
- ShotTypePanel の `KEYBOARD_MAP` に `'0'` は存在しないため競合なし（`'g'` → other）
- AnnotatorPage 側で `onHitterSelect: (hitter) => store.setHitter(hitter)` を渡す

---

## 7. 同一デバイスからの共有リンクアクセス修正

### 変更ファイル
- `backend/routers/sessions.py`
- `src/hooks/annotator/useSessionSharing.ts`
- `src/components/annotation/SessionShareModal.tsx`

### 原因
`coach_urls` は LAN IP ベースの URL のみ生成。同一 Windows PC から `http://192.168.x.x:8765/` にアクセスする際、Windows の TCP/IP スタックがループバック経路を遮断する場合がある。`localhost` 経由は常に動作する。

### sessions.py 修正
```python
# LAN IP URL（他デバイス用）に加え、localhost URL を常に末尾追加
coach_urls.append(f"http://localhost:{port}/#/annotator/{session.match_id}")
camera_sender_urls.append(f"http://localhost:{port}/#/camera/{session.session_code}")
```
LAN_MODE 無効時でも同一 PC からのアクセスは必ず機能する。

### useSessionSharing.ts 修正（rebaseUrl）
```typescript
const rebaseUrl = useCallback((url: string) => {
  if (!tunnelBase) return url
  try {
    const u = new URL(url)
    // localhost / 127.0.0.1 はトンネル経由不要 → そのまま返す
    if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') return url
    return tunnelBase + u.pathname + u.search + u.hash
  } catch { return url }
}, [tunnelBase])
```
Cloudflare Tunnel 有効時に localhost URL が誤って tunnel ベースに書き換えられるのを防ぐ。

### SessionShareModal.tsx 修正
localhost URL を LAN IP URL と分離して表示。

```tsx
const isLocalhost = (u: string) => /localhost|127\.0\.0\.1/.test(u)
const lanCoachUrls = coachUrls.filter(u => !isLocalhost(u))
const localCoachUrl = coachUrls.find(isLocalhost) ?? ''
const coachUrl = lanCoachUrls[0] ?? localCoachUrl  // QR は LAN IP 優先

// QR・URL の下に「同一PC用:」リンクを表示
{localCoachUrl && (
  <div className="flex items-center gap-1.5 mb-4">
    <p className={`text-[10px] ${noteColor} whitespace-nowrap`}>同一PC用:</p>
    <a href={localCoachUrl} target="_blank" rel="noopener noreferrer"
       className={`...text-blue-400 hover:text-blue-300`}>
      {localCoachUrl}
    </a>
  </div>
)}
```

---

## 適用要件

| 変更 | 反映に必要な操作 |
|---|---|
| `matches.py` (Pydantic fix) | バックエンド再起動 |
| `main.py` (MIME fix) | バックエンド再起動 |
| `sessions.py` (localhost URL) | バックエンド再起動 |
| `MatchListPage.tsx` (setQuery fix) | フロントエンドリビルド |
| `AnnotatorPage.tsx` (doubles display / hitter panel) | フロントエンドリビルド |
| `useKeyboard.ts` (7/8/9/0 shortcuts) | フロントエンドリビルド |
| `useSessionSharing.ts` (rebaseUrl) | フロントエンドリビルド |
| `SessionShareModal.tsx` (同一PC用リンク) | フロントエンドリビルド |

---

## 未対応・人間によるテストが必要な項目

- 実際の同一デバイスでの共有リンク動作確認（ブラウザで `http://localhost:8765/#/annotator/...` が開けるか）
- ダブルス試合での打者キーボードショートカット（7/8/9/0）動作確認
- LAN 別デバイス（iPhone 等）での QR コード読み取り → ページ表示確認
- フロントエンドリビルド後の動作確認（`npm run build`）
