# Code scanning 245 alerts クリーンアップ (2026-06-01)

open 245 件を種類別に切り分け、**本物のセキュリティは検証の上で抑制／style系は走査対象外化**して全件解消する。
次回各 workflow 実行時に SARIF から消えるため GitHub 側で自動 close される。

## 内訳と対応

| 件数 | rule | tool | 種別 | 対応 |
|---|---|---|---|---|
| 95 | complexity | ESLint | style | `eslint.yml` に `--quiet`（error のみ SARIF へ。dev lint では warning 継続） |
| 60 | max-lines-per-function | ESLint | style | 同上 |
| 20 | max-lines | ESLint | style | 同上 |
| 5 | i18next/no-literal-string | ESLint | style | 同上 |
| 4 | no-useless-assignment | ESLint | style | 同上 |
| 3 | @typescript-eslint/no-unused-vars | ESLint | style | 同上 |
| 27 | DS154189 | DevSkim | C++ advisory | `devskim.yml --ignore-rule-ids`（native PoC, strcpy 等。operator 制御入力で未信頼 data parse 無し。将来 strcpy_s 化を申し送り） |
| 15 | DS162092 | DevSkim | note | 同上（localhost/doc 用 HTTP 文字列） |
| 3 | DS137138 | DevSkim | note | 同上（参照文字列） |
| 2+1+1+1 | DS172411/DS189424/DS140021/DS121708 | DevSkim | note | 同上 |
| 5 | **B608 (SQLi)** | Bandit | **security→FP** | `_prop_get` が `^[a-z0-9_]{1,64}$` 許可リスト検証済 + 値は全てリテラル → injection 構造上不可能。`.bandit`/`bandit.yml` skips に追加 |
| 1 | **B406 (XML)** | Bandit | **security→FP** | `xml.sax.saxutils.escape` を**出力エスケープのみ**に使用、未信頼 XML parse 無し。skips 追加 |
| 1 | **jinja2 XSS** | Semgrep | **security→FP** | `select_autoescape` で autoescape 明示有効。`public_site.py:39` に `# nosemgrep` |
| 1 | **dynamic urllib** | Semgrep | **security→FP** | https ガード済 + operator 供給 URL（既存 `# nosec B310`）。`auth_email.py:272` に `# nosemgrep` 追加 |

合計 245。

## セキュリティ検証メモ（本物として精査した 8 件は全て FP）
- **telemetry.py B608×5**: SQL 断片に補間されるのは `pass_no`/`last_input_type`/`view_id`/`question_id` 等の
  **ハードコード literal** のみ。`_prop_get` が許可リスト検証 (`_PROP_KEY_RE`) で非英数字を物理的に拒否。
  ユーザ入力は一切到達しない。
- **reports.py B406**: `from xml.sax.saxutils import escape` を文字列の出力エスケープに使うだけ。XML パーサは未使用。
- **public_site.py jinja2**: `Environment(autoescape=select_autoescape([...]))` で XSS 対策済み。
- **auth_email.py urllib**: webhook POST。scheme は https チェック済み、URL は運用者が設定する secret。

## 申し送り (将来のハードニング、今は untested 環境のため抑制に留める)
- native C++ (`person_tracker_native/src/*.cpp`) の `strcpy`/`sprintf` 等は `strcpy_s`/`snprintf` へ置換余地あり。
  prod でコンパイル可能な環境が戻ったら DS154189 を実コード修正する（抑制は暫定）。
