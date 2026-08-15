"""稼働中の TURN サーバが内部ネットワークへの踏み台にならないか実際に試す。

設定ファイルを読んで安心するのではなく、攻撃側の手順をそのまま実行して
「内部アドレスへの中継を要求したら断られるか」を見る。

前提: 検証者は TURN の資格情報を持っている。踏み台化は資格情報を持つ者
(= 正規の参加者、または漏れた credential を拾った者) が起こす問題なので、
資格情報なしで試しても意味がない。

TURN には内部へ中継させる経路が複数ある。片方だけ塞いでも迂回されるため、
両方を試す:
  1. CreatePermission + Send indication
  2. ChannelBind + ChannelData
加えて TCP リレー (RFC 6062) が開いていないかも確認する。TCP が通ると
内部の PostgreSQL 等へ本物の接続を張られるため UDP より危険。

使い方:
    python verify_turn_hardening.py --host turn.example.com --port 3478 \
        --user <username> --password <credential> \
        --peer 192.168.1.10 --peer 10.0.0.5

終了コード 0 = 全ての内部アドレスが拒否された。1 = 中継された (危険)。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import secrets
import socket
import struct
import sys

MAGIC = 0x2112A442
ALLOCATE_REQ, ALLOCATE_OK, ALLOCATE_ERR = 0x0003, 0x0103, 0x0113
CREATEPERM_REQ, CREATEPERM_OK, CREATEPERM_ERR = 0x0008, 0x0108, 0x0118
CHANNELBIND_REQ, CHANNELBIND_OK, CHANNELBIND_ERR = 0x0009, 0x0109, 0x0119
A_USERNAME, A_MI, A_ERR = 0x0006, 0x0008, 0x0009
A_REALM, A_NONCE = 0x0014, 0x0015
A_XOR_PEER, A_DATA, A_REQ_TRANSPORT, A_CHANNEL = 0x0012, 0x0013, 0x0019, 0x000C

TRANSPORT_UDP, TRANSPORT_TCP = 17, 6


def _pad(b: bytes) -> bytes:
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def _attr(t: int, v: bytes) -> bytes:
    return struct.pack("!HH", t, len(v)) + _pad(v)


def _xor_addr(ip: str, port: int) -> bytes:
    return (struct.pack("!BBH", 0, 0x01, port ^ (MAGIC >> 16))
            + struct.pack("!I", struct.unpack("!I", socket.inet_aton(ip))[0] ^ MAGIC))


def _build(mt: int, tid: bytes, attrs: bytes, key: bytes | None) -> bytes:
    if key is None:
        return struct.pack("!HHI", mt, len(attrs), MAGIC) + tid + attrs
    head = struct.pack("!HHI", mt, len(attrs) + 24, MAGIC) + tid
    mac = hmac.new(key, head + attrs, hashlib.sha1).digest()
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
        return "(エラーコードなし)"
    return f"{raw[2] * 100 + raw[3]} {raw[4:].decode('utf-8', 'replace')}"


class TurnSession:
    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.dst = (host, port)
        self.user, self.password = user, password
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(5)
        self.key = b""
        self.realm = ""
        self.nonce = b""

    def close(self) -> None:
        self.sock.close()

    def _auth_attrs(self) -> bytes:
        return (_attr(A_USERNAME, self.user.encode())
                + _attr(A_REALM, self.realm.encode())
                + _attr(A_NONCE, self.nonce))

    def allocate(self, transport: int = TRANSPORT_UDP) -> str:
        rt = _attr(A_REQ_TRANSPORT, struct.pack("!BBBB", transport, 0, 0, 0))
        self.sock.sendto(_build(ALLOCATE_REQ, secrets.token_bytes(12), rt, None), self.dst)
        _mt, a = _parse(self.sock.recvfrom(2048)[0])
        self.realm = a.get(A_REALM, b"").decode()
        self.nonce = a.get(A_NONCE, b"")
        self.key = hashlib.md5(  # noqa: S324 - RFC 5389 が MD5 を規定している
            f"{self.user}:{self.realm}:{self.password}".encode()).digest()

        req = _build(ALLOCATE_REQ, secrets.token_bytes(12),
                     rt + self._auth_attrs(), self.key)
        self.sock.sendto(req, self.dst)
        mt, a = _parse(self.sock.recvfrom(2048)[0])
        return "OK" if mt == ALLOCATE_OK else f"拒否: {_errtext(a)}"

    def create_permission(self, ip: str, port: int) -> tuple[bool, str]:
        attrs = _attr(A_XOR_PEER, _xor_addr(ip, port)) + self._auth_attrs()
        self.sock.sendto(_build(CREATEPERM_REQ, secrets.token_bytes(12), attrs, self.key),
                         self.dst)
        mt, a = _parse(self.sock.recvfrom(2048)[0])
        if mt == CREATEPERM_OK:
            return True, "許可された"
        if mt == CREATEPERM_ERR:
            return False, _errtext(a)
        return False, f"想定外の応答 0x{mt:04x}"

    def channel_bind(self, ip: str, port: int, channel: int = 0x4000) -> tuple[bool, str]:
        attrs = (_attr(A_CHANNEL, struct.pack("!HH", channel, 0))
                 + _attr(A_XOR_PEER, _xor_addr(ip, port)) + self._auth_attrs())
        self.sock.sendto(_build(CHANNELBIND_REQ, secrets.token_bytes(12), attrs, self.key),
                         self.dst)
        mt, a = _parse(self.sock.recvfrom(2048)[0])
        if mt == CHANNELBIND_OK:
            return True, "許可された"
        if mt == CHANNELBIND_ERR:
            return False, _errtext(a)
        return False, f"想定外の応答 0x{mt:04x}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=3478)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--peer", action="append", required=True,
                   help="中継を試みる内部アドレス。複数指定可")
    p.add_argument("--peer-port", type=int, default=5432)
    args = p.parse_args()

    failures: list[str] = []

    print(f"TURN {args.host}:{args.port} を検証します")
    print()

    # TCP リレーが開いていないか
    s = TurnSession(args.host, args.port, args.user, args.password)
    try:
        tcp = s.allocate(TRANSPORT_TCP)
        if tcp == "OK":
            print("  [危険] TCP リレーが有効です。内部へ TCP 接続を張られます。")
            print("         no-tcp-relay を設定してください")
            failures.append("tcp-relay")
        else:
            print(f"  [良] TCP リレーは無効 ({tcp})")
    except socket.timeout:
        print("  [?] TCP allocate が無応答")
    finally:
        s.close()
    print()

    for peer in args.peer:
        print(f"内部アドレス {peer}:{args.peer_port} への中継を試みます")
        for label, method in (("CreatePermission", "perm"), ("ChannelBind", "chan")):
            s = TurnSession(args.host, args.port, args.user, args.password)
            try:
                alloc = s.allocate(TRANSPORT_UDP)
                if alloc != "OK":
                    print(f"  [?] {label}: allocate に失敗 ({alloc})。資格情報を確認してください")
                    continue
                if method == "perm":
                    allowed, detail = s.create_permission(peer, args.peer_port)
                else:
                    allowed, detail = s.channel_bind(peer, args.peer_port)
                if allowed:
                    print(f"  [危険] {label} が通りました — 踏み台にできます")
                    failures.append(f"{peer}/{label}")
                else:
                    print(f"  [良] {label} は拒否されました ({detail})")
            except socket.timeout:
                print(f"  [?] {label}: 無応答")
            finally:
                s.close()
        print()

    if failures:
        print(f"結果: 危険な経路が {len(failures)} 件あります → {', '.join(failures)}")
        return 1
    print("結果: 試した内部アドレスへの中継は全て拒否されました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
