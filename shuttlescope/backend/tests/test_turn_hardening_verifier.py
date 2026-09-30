from __future__ import annotations

import importlib.util
import ipaddress
from pathlib import Path
import socket
import struct


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra" / "turn" / "verify_turn_hardening.py"
SPEC = importlib.util.spec_from_file_location("verify_turn_hardening", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
turn_verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(turn_verify)


def test_v4_embedding_probes_are_all_ipv6_and_cover_expected_prefixes():
    rows = turn_verify._v4_in_v6_notations("10.0.0.1")
    labels = {label for _, label in rows}
    addresses = [ipaddress.ip_address(addr) for addr, _ in rows]

    assert len(rows) == 6
    assert all(addr.version == 6 for addr in addresses)
    assert "IPv4-compatible ::x.x.x.x" in labels
    assert "Teredo 2001::/32" in labels
    assert any(addr in ipaddress.ip_network("2001::/32") for addr in addresses)
    assert any(addr in ipaddress.ip_network("2002::/16") for addr in addresses)
    assert any(addr in ipaddress.ip_network("64:ff9b::/96") for addr in addresses)
    assert any(addr in ipaddress.ip_network("64:ff9b:1::/48") for addr in addresses)


def test_resolve_host_ips_returns_concrete_deduplicated_addresses(monkeypatch):
    def fake_getaddrinfo(host, port, family, socktype):
        assert host == "turn.example.test"
        assert port == 3478
        assert family == socket.AF_UNSPEC
        assert socktype == socket.SOCK_DGRAM
        return [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("203.0.113.8", port)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("203.0.113.8", port)),
            (socket.AF_INET6, socket.SOCK_DGRAM, 17, "", ("2001:db8::8", port, 0, 0)),
        ]

    monkeypatch.setattr(turn_verify.socket, "getaddrinfo", fake_getaddrinfo)

    assert turn_verify._resolve_host_ips("turn.example.test", 3478) == [
        "203.0.113.8",
        "2001:db8::8",
    ]


def test_turn_constructor_uses_resolved_socket_family(monkeypatch):
    monkeypatch.setattr(
        turn_verify.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET6,
                socket.SOCK_DGRAM,
                socket.IPPROTO_UDP,
                "",
                ("2001:db8::20", 3478, 0, 0),
            )
        ],
    )

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.family = family
            self.socktype = socktype
            self.proto = proto
            self.timeout = None

        def settimeout(self, value):
            self.timeout = value

        def close(self):
            pass

    monkeypatch.setattr(turn_verify.socket, "socket", FakeSocket)
    t = turn_verify.Turn("turn.example.test", 3478, "u", "p")
    assert t.sock.family == socket.AF_INET6
    assert t.dst == ("2001:db8::20", 3478, 0, 0)
    assert t.sock.timeout == 5


def test_coturn_template_keeps_required_hardening_directives():
    cfg = (ROOT / "infra" / "turn" / "coturn.conf.example").read_text(
        encoding="utf-8"
    )
    active = [
        line.strip()
        for line in cfg.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    required = {
        "use-auth-secret",
        "no-multicast-peers",
        "no-tcp-relay",
        "no-cli",
    }
    assert required.issubset(active)
    # coturn 4.6.2 has only positive web-admin; web admin is disabled by
    # default. no-web-admin is invalid and silently ignored after a warning.
    assert "no-web-admin" not in active
    assert not any(
        line == "web-admin"
        or line.startswith("web-admin=")
        or line.startswith("web-admin-listen-on-workers")
        for line in active
    )
    assert not any(line.startswith("allowed-peer-ip=") for line in active)
    assert any(line.startswith("user-quota=") for line in active)
    assert any(line.startswith("total-quota=") for line in active)
    assert any(line.startswith("max-bps=") for line in active)

    deny_lines = [line for line in active if line.startswith("denied-peer-ip=")]
    assert any("10.0.0.0-10.255.255.255" in line for line in deny_lines)
    assert any("192.168.0.0-192.168.255.255" in line for line in deny_lines)
    assert any("::ffff:" in line for line in deny_lines)
    assert any("64:ff9b::" in line for line in deny_lines)
    assert any("2002::-" in line for line in deny_lines)
    assert any("2001::-" in line for line in deny_lines)


def test_channel_bind_uses_a_fresh_channel_for_each_peer(monkeypatch):
    monkeypatch.setattr(
        turn_verify.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_DGRAM,
                socket.IPPROTO_UDP,
                "",
                ("127.0.0.1", 3478),
            )
        ],
    )

    sent = []
    responses = []

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            pass

        def settimeout(self, value):
            pass

        def sendto(self, data, dst):
            sent.append(data)

        def recvfrom(self, size):
            return responses.pop(0), ("127.0.0.1", 3478)

        def close(self):
            pass

    def ok_response():
        tid = b"x" * 12
        return turn_verify._build(
            turn_verify.CHANNELBIND_OK, tid, b"", None
        )

    monkeypatch.setattr(turn_verify.socket, "socket", FakeSocket)
    responses.extend([ok_response(), ok_response()])

    trn = turn_verify.Turn("127.0.0.1", 3478, "u", "p")
    trn.key = b"k"
    trn.realm = "r"
    trn.nonce = b"n"

    assert trn.channel_bind("10.0.0.1", 9999)[0] == "RELAYED"
    assert trn.channel_bind("10.0.0.2", 9999)[0] == "RELAYED"

    bind_messages = [sent[0], sent[2]]
    channels = []
    for message in bind_messages:
        _mt, attrs = turn_verify._parse(message)
        raw = attrs[turn_verify.A_CHANNEL]
        channel, _reserved = struct.unpack("!HH", raw)
        channels.append(channel)

    assert channels == [0x4000, 0x4001]



def test_positive_dns_relay_requires_real_return_traffic(monkeypatch):
    dns_id = 0x1234
    monkeypatch.setattr(turn_verify.secrets, "randbelow", lambda _n: dns_id)

    class FakeSocket:
        def __init__(self):
            self.query = None

        def recvfrom(self, _size):
            assert self.query is not None
            qid = struct.unpack("!H", self.query[:2])[0]
            reply = struct.pack(
                "!HHHHHH",
                qid,
                0x8180,  # response + recursion desired/available, rcode=0
                1,
                1,
                0,
                0,
            ) + b"\x00" * 8
            packet = turn_verify._build(
                turn_verify.DATA_IND,
                b"x" * 12,
                turn_verify._attr(turn_verify.A_DATA, reply),
                None,
            )
            return packet, ("127.0.0.1", 3478)

    class FakeTurn:
        def __init__(self, *_args, **_kwargs):
            self.sock = FakeSocket()
            self.closed = False

        def allocate(self, transport, family):
            assert transport == turn_verify.TRANSPORT_UDP
            assert family == turn_verify.FAMILY_V4
            return True, "OK"

        def create_permission_only(self, peer, port):
            assert peer == "1.1.1.1"
            assert port == 53
            return True, "OK"

        def send_indication(self, peer, port, payload):
            assert peer == "1.1.1.1"
            assert port == 53
            self.sock.query = payload

        def close(self):
            self.closed = True

    monkeypatch.setattr(turn_verify, "Turn", FakeTurn)

    ok, detail = turn_verify._positive_dns_relay(
        "turn.example.test",
        3478,
        "user",
        "password",
        "1.1.1.1",
        53,
        "example.com",
    )

    assert ok is True
    assert "dns_answers=1" in detail
    assert "response_bytes=" in detail


def test_ipv6_440_allocate_is_explicitly_blocked(monkeypatch):
    class FakeTurn:
        def __init__(self, *_args, **_kwargs):
            self.last_error_code = 0
            self.closed = False

        def allocate(self, transport, family):
            assert transport == turn_verify.TRANSPORT_UDP
            assert family == turn_verify.FAMILY_V6
            self.last_error_code = 440
            return False, "440 Address Family not Supported"

        def close(self):
            self.closed = True

    monkeypatch.setattr(turn_verify, "Turn", FakeTurn)
    pool = turn_verify._SessionPool(
        "turn.example.test",
        3478,
        "user",
        "password",
    )
    verdict, detail = turn_verify._probe(pool, "fd00::1", 5432, "perm")
    pool.close()

    assert verdict == "BLOCKED"
    assert "explicitly unsupported" in detail


def test_non_440_ipv6_allocate_failure_remains_untested(monkeypatch):
    class FakeTurn:
        def __init__(self, *_args, **_kwargs):
            self.last_error_code = 0

        def allocate(self, transport, family):
            self.last_error_code = 443
            return False, "443 Peer Address Family Mismatch"

        def close(self):
            pass

    monkeypatch.setattr(turn_verify, "Turn", FakeTurn)
    pool = turn_verify._SessionPool(
        "turn.example.test",
        3478,
        "user",
        "password",
    )
    verdict, detail = turn_verify._probe(pool, "fd00::1", 5432, "perm")
    pool.close()

    assert verdict == "UNTESTED"
    assert "allocate" in detail
