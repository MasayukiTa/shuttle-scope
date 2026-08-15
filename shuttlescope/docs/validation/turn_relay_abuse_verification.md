# TURN 踏み台化の実測検証 (2026-08-15)

**問い**: 自宅回線に UDP を開けて TURN を立てた場合、それを内部ネットワークへの
踏み台にされるのを本当に防げるのか。

**答え**: 防げる。ただし**既定設定では実際に踏み台にできる**ことと、
**IPv4 の deny を書いただけでは IPv6 表記で回避される**ことを実測で確認した。
`denied-peer-ip` は「入れておくと良い設定」ではなく、入れないと成立する攻撃を
止める唯一の制御である。

関連: `docs/design/MEDIA_PATH_v1.md` 5.6 節 /
`infra/turn/coturn.conf.example` / `infra/turn/verify_turn_hardening.py`

---

## 検証環境

- coturn 4.6 系 (Alpine Linux 3.20 / WSL2)
- 攻撃側は自作の TURN クライアント (RFC 5766/8656/6156 準拠の生メッセージ)
- 「内部サービス」役: IPv4/IPv6 の UDP を待ち受け、受信内容を記録するプロセス
  - IPv4: `172.24.51.174:9999` (RFC1918)
  - IPv6: `fd00::1:9999` (ULA。dummy インターフェースに付与)
- 攻撃者は **TURN の資格情報を持っている**前提。踏み台化は資格情報を持つ者が
  起こす問題なので、資格情報なしで試しても意味がない。
  現行 `backend/routers/tunnel.py` は Settings の固定 credential をそのまま
  返しており、この前提は現実的

## 結果 (全経路、対照つき)

「deny 無し」で通り「deny 有り」で止まることを、経路ごとに確認した。

| 攻撃経路 | deny 無し | 完全な deny 有り |
|---|---|---|
| IPv4 RFC1918 / CreatePermission | **到達** | 403 Forbidden IP |
| IPv4 RFC1918 / ChannelBind | **到達** | 403 Forbidden IP |
| **IPv4-mapped IPv6 (`::ffff:172.24.51.174`) / 両経路** | **到達** | 403 Forbidden IP |
| **IPv6 ULA (`fd00::1`) / 両経路** | **到達** | 403 Forbidden IP |
| IPv6 link-local (`fe80::1`) | **到達** | 403 Forbidden IP |
| ブロードキャスト `255.255.255.255` / 両経路 | **到達** | 403 Forbidden IP |
| `0.0.0.0` | 403 (既定で拒否) | 403 |
| IPv6 loopback `::1` | 403 (既定で拒否) | 403 |
| TURN 自身 | 403 (既定で拒否) | 403 |
| TCP リレー (RFC 6062) | 400 (この構成では無効) | 同左 |
| 認証なし Allocate | 401 Unauthorized | 401 |

最終確認では、脆弱構成で **8 経路が中継可能** (終了コード 1)、
完全な deny を入れた構成で **全経路拒否** (終了コード 0)。

## 無効だった検証を 2 つ記録する

**攻撃が成立することを先に示せない検証は、防御の証明にならない。**
以下はどちらも「防御が効いた」ように見えて、実際は別の理由で止まっていた。

1. **peer に `127.0.0.1` を使った回**
   防御なし構成でも 403 になった。coturn は loopback を既定で拒否する
   (`--allow-loopback-peers` が opt-in) ため、こちらの設定とは無関係に
   止まっていた。RFC1918 に変えて測り直した。

2. **IPv6 の peer を IPv4 の割当で試した回**
   全て `443 Peer Address Family Mismatch` になった。これは deny が
   効いたのではなく、割当の address family が違うので**検査に到達して
   いなかった**。RFC 6156 の `REQUESTED-ADDRESS-FAMILY` で IPv6 の割当を
   要求してからやり直したところ、**deny 無しでは到達した**。

このため `verify_turn_hardening.py` は 443 を「安全」ではなく
**「未検証」**として扱い、未検証が残ったら終了コード 1 を返す。

## 発見した欠陥 (このリポジトリの成果物)

初版の `coturn.conf.example` には **`denied-peer-ip=::ffff:0.0.0.0-::ffff:255.255.255.255`
が無かった**。IPv6 の ULA / link-local だけを塞いでいたため、攻撃者が
IPv6 の割当を取って内部 IPv4 を `::ffff:` 表記で指定すれば素通りする状態だった。
実測で到達を確認し、当該行を追加した。

**設定を書いただけでは分からない類の穴であり、実際に攻撃してみるまで
気づけなかった。**

## ここから言えること

1. **既定の coturn は踏み台になる。** LAN 上の PostgreSQL、ルータ管理画面、
   プリンタ、IoT 機器に UDP で到達できる
2. **経路は 1 つではない。** CreatePermission / ChannelBind / IPv6 表記 /
   IPv4-mapped / ブロードキャストと、少なくとも 5 系統ある。
   1 つ塞いで安心する発想自体が危険
3. **denylist 方式の宿命として、表記の網羅性が防御の強さを決める。**
   新しい表記が見つかれば穴になる
4. TCP リレーはこの構成では無効だったが、**明示的に `no-tcp-relay` を書く**

## 未検証 (正直に残す)

- **実際の本番ホストとルータ構成では未実施。** UDP を開ける前に
  `verify_turn_hardening.py` を本番へ向けて走らせ、終了コード 0 を確認すること
- **本番ホストがネイティブ IPv6 を持つ場合**、IPv4 のポート転送とは無関係に
  外部から直接到達できる可能性がある。「UDP 49160-49300 だけ開いている」という
  前提自体が崩れるので、ルータの IPv6 ファイアウォールを別途確認すること
- 帯域の踏み倒し (credential を拾われて中継に使われる) は `denied-peer-ip` では
  防げない。短命 credential と quota で対処する
- coturn の既知 CVE に対する最低バージョンの精査は未実施
- 事前認証 (認証前に処理されるパケットの解析) の攻撃面は未評価

## 運用への反映

- `infra/turn/coturn.conf.example` — 実測で有効性を確認した設定。
  `use-auth-secret` の時刻ベース一時 credential を既定にし、静的 `user=` を使わない
- `infra/turn/verify_turn_hardening.py` — 同じ攻撃を稼働中サーバへ仕掛ける。
  中継されたら 1、未検証が残っても 1。**脆弱構成で 8 件検出することを確認済み**
- 未修正の関連欠陥: `backend/routers/tunnel.py` が固定 TURN credential を
  そのまま返している。短命 HMAC 方式へ変える必要がある
