"""稼働中の TURN サーバが内部ネットワークへの踏み台にならないか実際に試す。

設定ファイルを読んで安心するのではなく、攻撃側の手順をそのまま実行して
「内部アドレスへの中継を要求したら断られるか」を見る。

前提: 検証者は TURN の資格情報を持っている。踏み台化は資格情報を持つ者
(= 正規の参加者、または漏れた credential を拾った者) が起こす問題なので、
資格情報なしで試しても意味がない。

試す経路 (どれか 1 つでも通れば内部へ届く):
  1. CreatePermission + Send indication
  2. ChannelBind + ChannelData
  3. IPv6 の割当を要求してから IPv6 の内部アドレス
  4. IPv4-mapped IPv6 (::ffff:10.0.0.1) — IPv4 の deny を書いただけでは
     素通りする。実測で確認済み
  5. ブロードキャスト / 0.0.0.0 / TURN 自身
  6. TCP リレー (RFC 6062) — 通ると内部へ本物の TCP 接続を張られる
  7. 認証なしの Allocate

**443 Peer Address Family Mismatch を「安全」と数えないこと。**
それは deny が効いたのではなく、割当の address family が違うので
検査に到達していないだけ。本スクリプトは宛先の family に合わせて
割当を要求し、それでも 443 が返る場合は「未検証」として報告する。

使い方:
    python verify_turn_hardening.py --host turn.example.com --port 3478 \
        --user <username> --password <credential> \
        --peer 192.168.1.10 --peer 10.0.0.5 --peer fd00::1

終了コード 0 = 中継された経路なし。1 = 中継された、または未検証が残った。

検証記録: docs/validation/turn_relay_abuse_verification.md
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import secrets
import socket
import struct
import sys
from typing import Optional

MAGIC = 0x2112A442
ALLOCATE_REQ, ALLOCATE_OK = 0x0003, 0x0103
CREATEPERM_REQ, CREATEPERM_OK, CREATEPERM_ERR = 0x0008, 0x0108, 0x0118
CHANNELBIND_REQ, CHANNELBIND_OK, CHANNELBIND_ERR = 0x0009, 0x0109, 0x0119
SEND_IND = 0x0016
A_USERNAME, A_MI, A_ERR = 0x0006, 0x0008, 0x0009
A_REALM, A_NONCE = 0x0014, 0x0015
A_XOR_PEER, A_DATA, A_CHANNEL = 0x0012, 0x0013, 0x000C
A_REQ_TRANSPORT, A_REQ_ADDR_FAMILY = 0x0019, 0x0017

TRANSPORT_UDP, TRANSPORT_TCP = 17, 6
FAMILY_V4, FAMILY_V6 = 0x01, 0x02


def _pad(b: bytes) -> bytes:
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def _attr(t: int, v: bytes) -> bytes:
    return struct.pack("!HH", t, len(v)) + _pad(v)


def _xor_peer(ip_str: str, port: int, tid: bytes) -> bytes:
    ip = ipaddress.ip_address(ip_str)
    xport = port ^ (MAGIC >> 16)
    if ip.version == 4:
        return (struct.pack("!BBH", 0, FAMILY_V4, xport)
                + struct.pack("!I", int(ip) ^ MAGIC))
    mask = int.from_bytes(struct.pack("!I", MAGIC) + tid, "big")
    return (struct.pack("!BBH", 0, FAMILY_V6, xport)
            + (int(ip) ^ mask).to_bytes(16, "big"))


def _build(mt: int, tid: bytes, attrs: bytes, key: bytes | None) -> bytes:
    if key is None:
        return struct.pack("!HHI", mt, len(attrs), MAGIC) + tid + attrs
    head = struct.pack("!HHI", mt, len(attrs) + 24, MAGIC) + tid
    # MESSAGE-INTEGRITY は RFC 5389 が HMAC-SHA1 を規定している。こちらが
    # 選べるものではなく、変えるとサーバが検証に失敗する。
    mac = hmac.new(key, head + attrs, hashlib.sha1).digest()  # noqa: S324  # nosec B324  # nosemgrep  # DevSkim: ignore DS126858
    a2 = attrs + _attr(A_MI, mac)
    return struct.pack("!HHI", mt, len(a2), MAGIC) + tid + a2


def _parse(data: bytes) -> tuple[int, dict[int, bytes]]:
    mt, ln, _ = struct.unpack("!HHI", data[:8])
    out: dict[int, bytes] = {}
    i, end = 20, 20 + ln
    while i + 4 <= end:
        t, l2 = struct.unpack("!HH", data[i:i + 4])
        out[t] = data[i + 4:i + 4 + l2]
        i += 4 + l2 + ((4 - l2 % 4) % 4)
    return mt, out


def _errtext(a: dict[int, bytes]) -> str:
    raw = a.get(A_ERR)
    if not raw or len(raw) < 4:
        return "(コードなし)"
    return f"{raw[2] * 100 + raw[3]} {raw[4:].decode('utf-8', 'replace')}"


def _err_code(a: dict[int, bytes]) -> int:
    raw = a.get(A_ERR)
    return raw[2] * 100 + raw[3] if raw and len(raw) >= 4 else 0


class Turn:
    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.dst, self.user, self.password = (host, port), user, password
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(5)
        self.key, self.realm, self.nonce = b"", "", b""

    def close(self) -> None:
        self.sock.close()

    def _auth(self) -> bytes:
        return (_attr(A_USERNAME, self.user.encode())
                + _attr(A_REALM, self.realm.encode()) + _attr(A_NONCE, self.nonce))

    def allocate(self, transport: int = TRANSPORT_UDP,
                 family: int | None = None) -> tuple[bool, str]:
        rt = _attr(A_REQ_TRANSPORT, struct.pack("!BBBB", transport, 0, 0, 0))
        if family is not None:
            rt += _attr(A_REQ_ADDR_FAMILY, struct.pack("!BBBB", family, 0, 0, 0))
        self.sock.sendto(_build(ALLOCATE_REQ, secrets.token_bytes(12), rt, None), self.dst)
        _mt, a = _parse(self.sock.recvfrom(2048)[0])
        self.realm = a.get(A_REALM, b"").decode()
        self.nonce = a.get(A_NONCE, b"")
        # long-term credential の鍵は RFC 5389 が MD5(username:realm:password)
        # と規定している。強度の選択ではなくプロトコル定数。
        # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
        self.key = hashlib.md5(  # noqa: S324  # nosec B324  # DevSkim: ignore DS126858
            f"{self.user}:{self.realm}:{self.password}".encode()).digest()
        self.sock.sendto(
            _build(ALLOCATE_REQ, secrets.token_bytes(12), rt + self._auth(), self.key),
            self.dst)
        mt, a = _parse(self.sock.recvfrom(2048)[0])
        return (True, "OK") if mt == ALLOCATE_OK else (False, _errtext(a))

    def create_permission(self, ip: str, port: int) -> tuple[str, str]:
        tid = secrets.token_bytes(12)
        attrs = _attr(A_XOR_PEER, _xor_peer(ip, port, tid)) + self._auth()
        self.sock.sendto(_build(CREATEPERM_REQ, tid, attrs, self.key), self.dst)
        mt, a = _parse(self.sock.recvfrom(2048)[0])
        if mt == CREATEPERM_OK:
            tid2 = secrets.token_bytes(12)
            self.sock.sendto(
                _build(SEND_IND, tid2,
                       _attr(A_XOR_PEER, _xor_peer(ip, port, tid2))
                       + _attr(A_DATA, b"TURN-HARDENING-PROBE"), None), self.dst)
            return "RELAYED", "許可された"
        if _err_code(a) == 443:
            return "UNTESTED", _errtext(a)
        return "BLOCKED", _errtext(a)

    def channel_bind(self, ip: str, port: int) -> tuple[str, str]:
        tid = secrets.token_bytes(12)
        attrs = (_attr(A_CHANNEL, struct.pack("!HH", 0x4000, 0))
                 + _attr(A_XOR_PEER, _xor_peer(ip, port, tid)) + self._auth())
        self.sock.sendto(_build(CHANNELBIND_REQ, tid, attrs, self.key), self.dst)
        mt, a = _parse(self.sock.recvfrom(2048)[0])
        if mt == CHANNELBIND_OK:
            self.sock.sendto(struct.pack("!HH", 0x4000, 20) + b"TURN-HARDENING-PROBE",
                             self.dst)
            return "RELAYED", "許可された"
        if _err_code(a) == 443:
            return "UNTESTED", _errtext(a)
        return "BLOCKED", _errtext(a)


def _v4_in_v6_notations(v4: str) -> list[tuple[str, str]]:
    """IPv4 アドレスを IPv6 の中に埋め込む書き方を並べる。

    denylist は表記ごとに書かないと効かない。`::ffff:` だけ塞いだ状態で
    6to4 と NAT64 が ACL を通過することを実測している。
    """
    n = int(ipaddress.ip_address(v4))
    hi, lo = (n >> 16) & 0xFFFF, n & 0xFFFF
    return [
        (f"::ffff:{v4}", "IPv4-mapped ::ffff:"),
        (str(ipaddress.ip_address(n)), "IPv4-compatible ::x.x.x.x"),
        (f"2002:{hi:x}:{lo:x}::1", "6to4 2002::/16"),
        (str(ipaddress.ip_address(int(ipaddress.ip_address("64:ff9b::")) | n)),
         "NAT64 well-known prefix"),
        (str(ipaddress.ip_address(int(ipaddress.ip_address("64:ff9b:1::")) | n)),
         "NAT64 local-use prefix"),
    ]


class _SessionPool:
    """address family ごとに割当を 1 つだけ作って使い回す。

    宛先ごとに新しい Allocate を投げると、まともに quota を設定したサーバでは
    486 Allocation Quota Reached で検査が完走しない (実測)。本物のクライアントも
    1 つの割当に対して複数の peer permission を張るので、こちらが正しい。
    """

    def __init__(self, host: str, port: int, user: str, pw: str) -> None:
        self._args = (host, port, user, pw)
        self._sessions: dict[int, Optional[Turn]] = {}
        self._errors: dict[int, str] = {}

    def get(self, family: int) -> tuple[Optional[Turn], str]:
        if family in self._sessions:
            return self._sessions[family], self._errors.get(family, "")
        t = Turn(*self._args)
        try:
            ok, detail = t.allocate(TRANSPORT_UDP, family)
            if not ok and family == FAMILY_V6:
                # v6 の割当を持たないサーバもある。その場合は検査不能と記録する
                t.close()
                self._sessions[family] = None
                self._errors[family] = detail
                return None, detail
            if not ok:
                t.close()
                self._sessions[family] = None
                self._errors[family] = detail
                return None, detail
            self._sessions[family] = t
            return t, ""
        except Exception as exc:  # noqa: BLE001
            t.close()
            self._sessions[family] = None
            self._errors[family] = str(exc)
            return None, str(exc)

    def close(self) -> None:
        for t in self._sessions.values():
            if t is not None:
                t.close()


def _probe(pool: "_SessionPool", peer: str, peer_port: int,
           method: str) -> tuple[str, str]:
    """宛先の family に合った割当を使い回して 1 経路を試す。"""
    family = FAMILY_V6 if ipaddress.ip_address(peer).version == 6 else FAMILY_V4
    t, err = pool.get(family)
    if t is None:
        return "UNTESTED", f"allocate 不可 ({err})"
    try:
        return (t.create_permission(peer, peer_port) if method == "perm"
                else t.channel_bind(peer, peer_port))
    except socket.timeout:
        return "UNTESTED", "無応答"
    except Exception as exc:  # noqa: BLE001
        return "UNTESTED", f"例外: {exc}"


def main() -> int:
    p = argparse.ArgumentParser(description="TURN 踏み台化の実地確認")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=3478)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--peer", action="append", required=True,
                   help="中継を試みる内部アドレス (IPv4/IPv6)。複数指定可")
    p.add_argument("--peer-port", type=int, default=5432)
    args = p.parse_args()

    relayed: list[str] = []
    untested: list[str] = []

    print(f"TURN {args.host}:{args.port} を検証します\n")

    # 認証なしで確保できないこと
    t = Turn(args.host, args.port, args.user, args.password)
    try:
        rt = _attr(A_REQ_TRANSPORT, struct.pack("!BBBB", TRANSPORT_UDP, 0, 0, 0))
        t.sock.sendto(_build(ALLOCATE_REQ, secrets.token_bytes(12), rt, None), t.dst)
        mt, a = _parse(t.sock.recvfrom(2048)[0])
        if mt == ALLOCATE_OK:
            print("  [危険] 認証なしで Allocate できました")
            relayed.append("unauthenticated-allocate")
        else:
            print(f"  [良] 認証なしの Allocate は拒否 ({_errtext(a)})")
    except socket.timeout:
        print("  [?] 認証なし Allocate が無応答")
        untested.append("unauthenticated-allocate")
    finally:
        t.close()

    # TCP リレーが開いていないこと
    t = Turn(args.host, args.port, args.user, args.password)
    try:
        ok, detail = t.allocate(TRANSPORT_TCP)
        if ok:
            print("  [危険] TCP リレーが有効です。内部へ TCP 接続を張られます")
            print("         no-tcp-relay を設定してください")
            relayed.append("tcp-relay")
        else:
            print(f"  [良] TCP リレーは無効 ({detail})")
    except socket.timeout:
        print("  [?] TCP allocate が無応答")
        untested.append("tcp-relay")
    finally:
        t.close()
    print()

    # 内部アドレスへの中継。IPv4 は「IPv6 の中に埋め込む」表記を全て試す。
    # ::ffff: だけ塞いでも 6to4 / NAT64 / Teredo / IPv4-compatible は
    # 別表記なので素通りする (実測で 6to4 と NAT64 が通過した)。
    targets: list[tuple[str, str]] = []
    for peer in args.peer:
        targets.append((peer, peer))
        if ipaddress.ip_address(peer).version == 4:
            for notation, label in _v4_in_v6_notations(peer):
                targets.append((notation, f"{peer} ({label})"))
    # 中継を試みる「宛先」であって待受アドレスではない (bind していない)
    for extra in ("255.255.255.255", "0.0.0.0", args.host):  # nosec B104
        targets.append((extra, extra))

    pool = _SessionPool(args.host, args.port, args.user, args.password)
    for addr, label in targets:
        print(f"{label} への中継")
        for name, method in (("CreatePermission", "perm"), ("ChannelBind", "chan")):
            verdict, detail = _probe(pool, addr, args.peer_port, method)
            if verdict == "RELAYED":
                print(f"  [危険] {name} が通りました — 踏み台にできます")
                relayed.append(f"{addr}/{name}")
            elif verdict == "UNTESTED":
                print(f"  [未検証] {name}: {detail}")
                untested.append(f"{addr}/{name}")
            else:
                print(f"  [良] {name} は拒否 ({detail})")
        print()

    pool.close()

    if relayed:
        print(f"結果: 中継できた経路が {len(relayed)} 件 → {', '.join(relayed)}")
        return 1
    if untested:
        print(f"結果: 未検証が {len(untested)} 件残りました → {', '.join(untested)}")
        print("      未検証は「安全」ではありません。攻撃者はそこから来ます")
        return 1
    print("結果: 試した全経路で中継は拒否されました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
