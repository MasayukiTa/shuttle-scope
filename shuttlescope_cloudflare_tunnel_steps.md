# ShuttleScope 公開手順メモ
## 独自ドメイン + Cloudflare Tunnel + 最小安全化

この文書は、`shuttle-scope.com` を取得済みの前提で、
ShuttleScope をまずは `app.shuttle-scope.com` で外から見えるようにするための最小手順をまとめたもの。

重要:
これは「とりあえず外から見えるようにする」ための手順であり、
今の ShuttleScope 全体をそのまま安全に公開する手順ではない。

最初の目的はこれだけ:

- 固定URLで外から見える
- 固定IPは不要
- 毎回 dev tunnel のURLを渡さなくてよい
- できるだけ危険な面は外へ出さない
- Cloudflare 側で前段ゲートをかける

---

## 0. 前提整理

この構成では、独自ドメインとトンネルは役割が違う。

### 独自ドメイン
- `shuttle-scope.com`
- これは単なる名前
- 看板であって、中身に自動でつながるわけではない

### Cloudflare Tunnel
- 自宅PCから Cloudflare 側へ接続を張る仕組み
- 外の人は Cloudflare にアクセスし、その通信が既存のトンネルを通って自宅PCに届く
- 固定IP不要
- 原則として自宅ルータのポート開放不要

### これで起きること
例えば `app.shuttle-scope.com` にアクセスすると:

外部ブラウザ
→ Cloudflare
→ Cloudflare Tunnel
→ 自宅PCの `http://localhost:XXXX`
→ ShuttleScope

---

## 1. まず決めること

最初から `shuttle-scope.com` 直下を本体にしない。
最初はサブドメインを使う。

### 推奨構成
- `shuttle-scope.com`
  - 説明ページまたは入口用
- `app.shuttle-scope.com`
  - 選手/コーチ/関係者が見る本体
- `admin.shuttle-scope.com`
  - 将来の管理面候補
  - 最初は作らない、または公開しない

### 今回の最初の目標
- `app.shuttle-scope.com` だけを外から見えるようにする

---

## 2. 今の ShuttleScope 側で確認すること

トンネルの前に、まずローカルで確実に動いていないと話にならない。

### 必須確認
1. 自宅PCで ShuttleScope が起動できる
2. ブラウザでローカルアクセスできる
3. 実際に表示したい画面が見える

### 例
- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://localhost:8765`
- Electron の内部サーバ等

### 注意
Cloudflare Tunnel は「ローカルで動いているもの」を外へ運ぶだけ。
ローカルで壊れているなら、外からも当然壊れる。

---

## 3. 今の段階で外へ出してよいもの / 出してはいけないもの

これが一番重要。

### 今の段階で外へ出してよい候補
- ログイン画面
- 選手/コーチ向けの閲覧画面
- review / dashboard の読み取り中心画面
- 室屋さんデータの閲覧デモ面
- スマホで価値が伝わる画面

### 今の段階で絶対にそのまま外へ出してはいけないもの
- cluster 管理系
- worker / ray 制御系
- `video_import/path` のようなローカルファイル操作
- auth の開発互換経路
- admin のみが触る設定画面
- DB保守、危険な設定変更、ARP/ハードウェア検出等

### 結論
今外へ出すのは「app の閲覧面だけ」に寄せる。
ShuttleScope 全体をそのまま公開しない。

---

## 4. Cloudflare でやることの全体像

やることは実は少ない。

1. ドメインを Cloudflare で管理する
2. 公開したいPCに `cloudflared` を入れる
3. named tunnel を作る
4. `app.shuttle-scope.com` をその tunnel に向ける
5. tunnel の先を `localhost` の ShuttleScope に向ける
6. Cloudflare Access をかける
7. スマホから確認する

---

## 5. cloudflared を入れる

公開したいPC、つまり ShuttleScope が動いているPCに `cloudflared` を入れる。

### 方針
- X1 AI 側で動かすのが自然
- 公開対象PCとトンネル実行PCは基本同じでよい
- まずは常駐サービス化しなくてよい
- 最初は手動起動で十分

### やること
- `cloudflared` をインストール
- コマンドが使えることを確認

### 最初に確認すること
- `cloudflared` コマンドが通る
- Cloudflare の対象アカウントにログインできる

---

## 6. Cloudflare にログインして tunnel を作る

### 概念
ここで作るのは、一時的な dev tunnel ではなく、名前付きの tunnel。

### やること
- Cloudflare アカウントに対して `cloudflared` を認証
- named tunnel を作成
- その tunnel に対して DNS レコードを作る

### 推奨の tunnel 名
- `shuttlescope-app`
- または `app-tunnel`

トンネル名は内部識別なので、あとで分かる名前でよい。

---

## 7. DNS を app.shuttle-scope.com に向ける

### やること
- `app.shuttle-scope.com` を tunnel に向ける
- これにより、外から `app.shuttle-scope.com` に来たアクセスが tunnel に流れる

### 重要
最初はトップドメイン直下ではなく `app.` を使う。
理由:
- 役割分離しやすい
- 将来 `admin.` や `viewer.` を足せる
- トップを説明ページや入口に残せる

---

## 8. tunnel の先を localhost に向ける

ここで「外から来たアクセスを、手元のどこに流すか」を定義する。

### 例
- `app.shuttle-scope.com` → `http://localhost:3000`
- `app.shuttle-scope.com` → `http://127.0.0.1:8765`

### 注意
- まずは `http` でよい
- 外から見る側は `https`
- ローカル側は `http://localhost:XXXX` でよいことが多い

### なぜこれでよいか
ブラウザ
→ Cloudflare までは `https`
Cloudflare
→ トンネル
→ 手元のアプリまでは内部経路

つまり、最初から自分で証明書地獄に入る必要はない。

---

## 9. http と https の整理

ここは誤解しやすいので分けて書く。

### 外から見ている人
- 基本 `https://app.shuttle-scope.com`
- 鍵マークあり
- つまり外部利用者視点では https

### 自宅PC上の ShuttleScope
- `http://localhost:3000` などで動いていてよい
- ここは最初は http でよい

### つまり
- 外側: https
- 内側: http localhost
- 最初はこれで十分

---

## 10. Cloudflare Access を必ず前段に置く

「数分だけ公開」は危ない。
必ず前段ゲートを置く。

### これは何か
ShuttleScope 本体のログイン画面に到達する前に、
Cloudflare 側で「そもそもこの人を通すか」を判定する仕組み。

### 最初のおすすめ
- 許可したメールアドレスだけ通す
- ワンタイムコードを送る
- 君と、実際に見せる数人だけ通す

### 二段構え
1. Cloudflare Access で入口を絞る
2. そのあと ShuttleScope 側でもログインさせる

### 理由
今の ShuttleScope はまだ公開面の分離が完全ではない。
だからアプリ内ログインだけに頼らない。

---

## 11. 最初の公開対象を絞る

これは技術より重要。

### 最初に見せるべきもの
- 室屋さんデータの閲覧
- review / dashboard の価値が伝わる画面
- スマホで見ても意味が分かる画面

### 最初に見せないもの
- cluster
- settings の危険項目
- local path import
- benchmark 管理
- worker 制御
- 管理者向け操作

### 基本方針
「最初に見せる app は read-mostly」
編集や危険操作は後回し。

---

## 12. 最小公開手順

実際の順番はこれでよい。

### Step 1
ShuttleScope をローカルで起動し、ブラウザで見えることを確認

### Step 2
`cloudflared` を X1 AI へ導入

### Step 3
Cloudflare にログイン認証

### Step 4
named tunnel を作成

### Step 5
`app.shuttle-scope.com` をその tunnel に向ける

### Step 6
tunnel の先を `http://localhost:XXXX` に設定

### Step 7
Cloudflare Access を `app.shuttle-scope.com` に適用

### Step 8
スマホ回線など、ローカルネットワーク外から `https://app.shuttle-scope.com` を開いて確認

---

## 13. スマホ確認のしかた

### 必須
- 自宅Wi-Fiを切る
- 4G / 5G など別回線で開く
- ちゃんと外から見えていることを確認

### 確認項目
- Access の前段認証が出るか
- その後に ShuttleScope のログインへ進めるか
- 室屋さんデータの対象画面が見えるか
- スマホでレイアウト破綻しないか

---

## 14. 今の段階でやらないこと

### やらないこと
- トップ `shuttle-scope.com` 直下に全部載せる
- 管理画面を外へ出す
- cluster / ray 系も同時に出す
- 単なるアプリ内パスワードだけで公開する
- 「数分だけだから」と Access なしで一時公開する
- 一気に本番構成を作ろうとする

### 理由
今必要なのは「固定URLで安全寄りに見せる最小構成」であって、
「全機能を本番公開すること」ではない。

---

## 15. 4月末までの現実的な目標

### 到達目標
- `app.shuttle-scope.com` で外から見える
- Cloudflare Access で入口制限
- ShuttleScope の内部ログインもある
- 室屋さんデータで価値が伝わる
- 選手/コーチがスマホから見て導入判断しやすい

### 到達目標ではないもの
- 完全な本番インフラ
- 完全なドメイン設計
- 危険面を含む全機能公開
- 完璧な商用品レベルのセキュリティ

---

## 16. 将来の整理イメージ

### 将来こう分けるとよい
- `shuttle-scope.com`
  - 説明ページ、入口
- `app.shuttle-scope.com`
  - 本体
- `admin.shuttle-scope.com`
  - 管理系、原則閉じる
- `viewer.shuttle-scope.com`
  - 必要なら閲覧専用
- `api.shuttle-scope.com`
  - 必要ならAPI専用

### ただし
最初から全部やらない。
まずは `app.` だけでよい。

---

## 17. 工数感

### トンネルだけつなぐ
- 1〜3時間程度

### Access まで入れる
- 半日程度

### ShuttleScope 側の公開面整理も含める
- 1〜2日程度

### 本当の難所
- tunnel 接続そのものではない
- 公開してよい面と危険面の分離が難所

---

## 18. Claude Code に投げられるもの / 投げられないもの

### Claude Code に投げやすいもの
- `cloudflared` 設定ファイルの雛形作成
- 起動スクリプト
- 環境変数切り替え
- 公開用モードの導入
- 危険画面の一時非表示
- 説明用ドキュメント作成

### Claude Code に投げても最後は人間が触るもの
- Cloudflare ダッシュボード設定
- DNS レコード作成
- Access の対象メール設定
- ドメイン設定
- 実際に何を公開するかの判断

---

## 19. 一番大事な結論

- 独自ドメインは単なる名前
- Cloudflare Tunnel は固定IPなしで自宅サーバへつなぐ道
- 外からは https で見せられる
- ローカル側は http localhost のままでよいことが多い
- 最初に公開するのは `app.shuttle-scope.com` だけ
- Cloudflare Access を必ず前段に置く
- ShuttleScope 全体をそのまま公開しない

---

## 20. 今すぐやる順番

1. ローカルで ShuttleScope が見えることを確認
2. `app.shuttle-scope.com` を公開対象に決める
3. `cloudflared` を導入
4. named tunnel 作成
5. DNS を tunnel に向ける
6. localhost の app へ転送設定
7. Cloudflare Access を有効化
8. スマホ外回線で確認
9. 見せてよい画面だけに絞る

この順でよい。
