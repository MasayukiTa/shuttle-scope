# Local LLM サービス仕様 (`app.shuttle-scope.com/#/llm`)

状態: ドラフト v0.1 / 2026-06-05。実装はフェーズ分割で進行。

## 1. 目的
管理者が限定的に許可したユーザのみが使える、Claude/ChatGPT 風の汎用 LLM チャットを
`app.shuttle-scope.com/#/llm` に新設する。
- 初期バックエンド = **NVIDIA NIM**（既存 `ExternalApiGenerator` の OpenAI 互換呼び出しを汎用化）。
- 将来 = **ローカル LLM（LM Studio / llama.cpp 等の OpenAI 互換エンドポイント）**へ差し替え可能。
- **コーディングエージェント**としても使える基礎（ツール/関数呼び出し抽象、ストリーミング）を用意。

既存の「バドミントン用インサイトチャット」（`insights_chat.py`、ドメイン特化・safety harness・
350トークン上限）とは**別系統**。汎用 LLM はドメインロックしない。ただし会話履歴の保持 UX は踏襲。

## 2. アクセスモデル（最重要・権限分離）
3 つのエンタイトルメントを admin が**ユーザ単位で細かく付与**する。付与は既存の
`player_page_access`（`GRANTABLE_PAGES`）を拡張して実現し、JWT の `page_access` クレームに載る。

| エンタイトルメント | キー | 意味 |
|---|---|---|
| 汎用LLM | `llm` | `/#/llm` の汎用 LLM チャットを使える |
| バドミントン | `badminton` | 通常のバドミントン解析アプリを使える（既存 role と併用）|

ユーザ種別と挙動:
- **LLM 専用**（`llm` のみ、`badminton` 無し）: ログイン後そのまま **`/#/llm` へリダイレクト**。
  バドミントン系ページ/ナビ/API には到達できない（サーバ側で拒否）。
- **両方**（`llm` + `badminton`）: 通常アプリ + ナビに **LLM タブ**（後述の Material Symbols アイコン）。
  そこから `/#/llm` へ。
- **バドミントン専用**（`badminton` のみ）: 汎用 LLM へのアクセスは**不可**。LLM はバドミントン専用
  インサイトチャット（既存）のみ。会話履歴は `/#/llm` 同様に保持する仕組みは用意するが、
  細かい設定（プロバイダ選択/システムプロンプト等）は触らせない。

アイコン: **必ず Google Material Symbols（プロジェクト規約 = MIcon のみ。emoji/lucide/独自SVG禁止）**。
LLM タブには `forum` か `smart_toy` 等の Material Symbol を `MIcon name=...` で指定し、subset 再生成。

## 3. バックエンド設計
### 3.1 プロバイダ抽象（`backend/services/llm/`）
- `base.py`: `LLMProvider` ABC。`stream_chat(messages, tools=None, **opts) -> Iterator[Delta]`、
  `chat(messages, tools=None) -> Message`。`ChatMessage`/`ToolCall`/`Delta` 型。
- `openai_compatible.py`: NIM / LM Studio / llama を **1 クラス**でカバー（base_url + api_key + model）。
  OpenAI 互換 `/chat/completions`。`stream=true` で SSE デルタを yield。tools(function calling) 対応。
- `registry.py`: 設定（既定プロバイダ）＋会話ごとの上書きで `LLMProvider` を解決。
- 既存 `ExternalApiGenerator`（insights）はそのまま温存。汎用側は本パッケージを使う。

### 3.2 設定（`config.py` / env）
- `LLM_PROVIDER`（`nim`|`local`|`openai`…既定 `nim`）、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。
- NIM は既存 `NVIDIA_BASE_URL`/`NVIDIA_API_KEY`/`NVIDIA_MODEL` をフォールバックに使う。
- ローカル切替は `LLM_PROVIDER=local` + `LLM_BASE_URL=http://127.0.0.1:1234/v1`（LM Studio 既定）等。

### 3.3 データモデル（insights とは別テーブル / migration 0042 予定）
- `LlmConversation`: id, user_id(FK), title, provider, model, system_prompt(nullable),
  created_at, last_used_at, deleted_at(soft delete)。
- `LlmTurn`: id, conversation_id(FK), seq, role(user/assistant/system/tool), content(Text),
  tool_calls(JSON nullable), tokens(int), created_at。

### 3.4 ルータ（`backend/routers/llm_chat.py`、全 endpoint でサーバ側 access 強制）
- `GET /api/llm/conversations` / `POST` / `DELETE /{id}`。
- `GET /api/llm/conversations/{id}/messages`。
- `POST /api/llm/conversations/{id}/messages`（**SSE ストリーミング**でトークンを返す）。
- アクセス: `require_llm_access`（`llm` グラント or admin）。会話は所有者 or admin のみ。
- レート制限 / トークン予算 / 監査ログ（insights のパターンを流用）。

### 3.5 コーディングエージェント基礎
- プロバイダ抽象に **tools(function calling)** を通す。ツール実行ループ（モデルが tool_call →
  サーバがツール実行 → 結果を会話に戻す）の足場を用意。初期はツール無し（純チャット）で動作、
  後で `read_file`/`run`/`search` 等の安全なツールを段階追加。

## 4. フロントエンド設計
- `src/pages/LlmChatPage.tsx`：ルート `/#/llm`。`PageAccessRoute pageKey="llm"` でゲート。
  UI は既存 `components/dashboard/advice_chat/*`（Composer/Bubble/TypingIndicator）を流用しつつ
  汎用チャット用に最小改変。**SSE ストリーミング**を `fetch().body.getReader()` で消費。
- ログイン後リダイレクト：`useAuth` の `pageAccess` を見て、`llm` のみ（`badminton` 無し）なら
  `/#/llm` へ自動遷移（ログイン成功ハンドラ or ルートガード）。
- ナビ：`badminton`+`llm` 両方のユーザにのみ LLM タブ（Material Symbols `MIcon`）を表示。
- i18n：`src/i18n/ja.json` にキー追加（TSX 直書き禁止）。

## 5. セキュリティ要件（実装後に必ず検証）
今回は特殊な権限分割のため、**権限上昇・横移動が不可能**であることを検証する:
- LLM 専用ユーザ（`llm` のみ）が **バドミントン系 API / admin API / 他ユーザの会話**に
  到達できないこと（403/404）。フロントゲートだけでなく**サーバ側で必ず拒否**。
- `page_access` は admin の grant 経由のみで増えない（自己付与不可）。`GRANTABLE_PAGES` で限定。
- 会話の所有者チェック（IDOR 不可）。
- JWT 改ざん/role 詐称が効かないこと（既存 verify_token に依存、追加サーフェスを増やさない）。
- LLM 専用ユーザはバドミントンのデータ（players/matches 等）を一切読めない。

## 6. テストユーザ（実装後にプロビジョニング）
- LLM 専用ユーザ: username `LLM`、`llm` グラントのみ、`badminton` 無し。
  パスワードはアプリの通常作成経路（ハッシュ保存）で設定。本番 DB へ admin 作成。
- 作成後、ログイン→`/#/llm` 直行、バドミントン系へ到達不可、を実機確認。

## 7. フェーズ
1. **アクセスモデル**: `GRANTABLE_PAGES` に `llm`/`badminton` 追加 + admin grant + JWT 反映 + サーバ側強制。
2. **バックエンド基盤**: プロバイダ抽象 + NIM + モデル + migration + ルータ（SSE）+ テスト。
3. **フロント**: `/#/llm` ページ + ルート/ナビ ゲート + ストリーミング UI + ログイン後リダイレクト。
4. **テストユーザ + セキュリティ検証**（§5/§6）。
5. **ローカル LLM 切替**（LM Studio/llama）動作確認。
6. **コーディングエージェント**: tools 実行ループ + 安全なツール群。

> 注: バドミントン専用ユーザ向けの「会話履歴保持」は既存 insights chat 側の履歴 UX を流用/強化する
> サブタスク。汎用 `/#/llm` とはテーブルもアクセスも分離する。
