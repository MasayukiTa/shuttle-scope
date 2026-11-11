# mid-rally autosave の確定ラリー上書き欠陥: 既修正の検証ノート (2026-11-11)

## 目的

途中保存 (mid-rally autosave、ラリー確定前の中間保存) が、確定ラリーの退避行を
上書きしてしまう欠陥を直すことが依頼だった。対象として指定されたファイルは
`shuttlescope/src/utils/midRallyAutosave.ts` および `shuttlescope/src/utils/offlineStrokeQueue.ts`
(周辺に `useOfflineSync.ts`)。想定していた成果物は、修正コード + 上書きを捕まえる
テスト + CI マニフェスト登録 + PR。

欠陥の内容:

- mid-rally autosave が確定ラリーと同じ owned 枠
  (`offlineStrokeQueueKey = <owner>/<match>/<set>/<rally>`) に `final=false` の
  中間 payload で退避していた。このため
  - (a) 確定ラリーの退避行を中間 payload が上書きし、`useOfflineSync` がそれを
    確定として送る。
  - (b) 中間保存の送信成功後の削除が、同じ owned キーを消し、先に退避してあった
    確定ラリーの行まで消す。
  - (c) 中間保存が確定と同じ冪等キー (`offline-...`) を使い、応答が確定を先取りする。

## 調査でわかったこと

この欠陥は既に **PR #337** (`fix(offline): mid-rally autosave が確定ラリーを
上書きしないよう別キューに分離`、commit `0ebf657`) として main にマージ済みだった。
依頼台帳が参照していた commit ハッシュはこのリポジトリの履歴には存在せず
(リベース/スカッシュで失われたものと見られる)、追跡は PR 番号と該当ファイルの
`git log` で行った。

`0ebf657` の内容 (origin/main の現在の状態で確認):

- `src/utils/offlineStrokeQueue.ts`
  - mid-rally 専用の別 prefix `mid/` を導入 (`MID_RALLY_PREFIX`、`midRallyQueueKey`)。
    確定 owned 枠とキーが衝突しない。
  - `isNonSendableKey` が `mid/` を `draft/` `unowned/` と同様に非送信扱いにする。
    これにより `listPendingForMatch` / `listPendingForUserStrict` /
    `countPendingForUserStrict` / `useOfflineSync` の自動再送対象から外れる。
  - mid 専用の冪等キー `midRallyIdempotencyKey = offline-mid-...` を確定キー
    `offline-...` と分離。中間保存の応答が確定ラリーの冪等キーを先取りしない。
  - `stashMidRally` / `removeMidRally` を追加。削除は mid/ 行だけに作用し、
    確定 owned 行には触れない。
- `src/utils/midRallyAutosave.ts`
  - `MidRallyAutosaver` に `suspended` フラグと `suspend()` を追加。確定 (ラリー保存)
    の stash/送信が始まったら以後の flush を無効化し、飛行中だった flush の
    成功後処理 (mid 枠削除・onSent) も抑止する。確定と中間保存の競合で確定内容が
    上書きされるのを防ぐ。
  - flush は mid 枠へ退避 (`stashMidRally`)、成功時は `removeMidRally` で mid 行だけ消す。
- テスト: `src/utils/__tests__/offlineStrokeQueue.midRallyOverwrite.test.ts` (新規) と
  `midRallyAutosave.test.ts` の追補。
- CI マニフェスト: `scripts/ci_test_manifest.d/offlineStrokeQueue.midRallyOverwrite.test.txt` を追加。

追加で、`useOfflineSync.ts` と `listPendingForUserStrict` も `isNonSendableKey` /
`payload != null` で draft・mid を除外しており、本文の無い行を `/strokes/batch` に
送って 422 を出す経路も塞がれている (関連する draftSkip テストも main に存在)。

## テスト内容の確認

`offlineStrokeQueue.midRallyOverwrite.test.ts` は、タイマー・送信を全モックした
実装の写しではなく、fake-indexeddb の実 DB に確定前の mid 行が残った状態で
再送ループ (useOfflineSync の送信部と同じ選別・冪等キー生成) を走らせ、次を確かめている:

- (1) mid 行と確定行が別キーに入り互いを上書きしない。sync で送られるのは確定
  payload (`final=true`) 1 件だけで、確定の冪等キー (`offline-...`) が使われ、
  mid の冪等キー (`offline-mid-...`) は使われない。
- (2) `removeMidRally` は mid 行だけを消し、確定 owned 行を残す。
- (3) `listPendingForUserStrict` / `countPendingForUserStrict` が draft 行と mid 行を
  除外し、確定行だけを本人の未送信として数える。
- `isNonSendableKey(mid/...) = true`、`isNonSendableKey(<owned>) = false`。

これは依頼が求めた「確定ラリー上書きを捕まえるテスト」の要件を満たしている。

## 考察・判断

- 依頼のコード修正・テスト・マニフェスト行はすべて既に main に存在するため、
  新規に作る差分が無い。無から差分を捏造して #337 と重複する PR を出すことは
  有害なので行わなかった。正しい成果は「既に #337 で解消済みであることの確認」である。
- テスト実行による緑確認を試みたが、この環境では検証用 worktree への
  `npm ci` が `STATUS_IN_PAGE_ERROR (0xC0000006)` で再現性をもって異常終了し、
  vitest を起動できなかった。したがってテストランナーでの裏取りは取れていない。
  ただし結論の根幹 (修正が #337 として main にマージ済み) はテスト実行に依存せず
  git の事実だけで確定しており、コードとテストの論理も main のソースを直接読んで
  確認した。
- 残課題: 恒久的 4xx で拒否された確定ラリーを操作者に見せる UI は別課題として
  コメントに明記されている (本件の範囲外)。

## 結論

mid-rally autosave の確定ラリー上書き欠陥は PR #337 (commit 0ebf657) で修正済み。
別キュー (mid/ prefix)・別冪等キー・確定割り込み時の suspend・mid 限定削除により、
(a)(b)(c) の 3 経路すべてが塞がれている。追加の修正 PR は不要。
