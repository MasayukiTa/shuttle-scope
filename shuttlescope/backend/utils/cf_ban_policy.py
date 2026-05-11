"""Cloudflare ban policy with VPN / Tor / CGNAT safety (R44).

問題:
  - 共有 VPN 出口 (NordVPN / ProtonVPN / Mullvad 等) を IP block すると、
    その VPN を使う数百〜数千の正規ユーザを巻き添えにする。
  - Tor 出口ノードは完全共有 IP なので、出口を block = Tor 経由の全アクセス遮断。
  - モバイルキャリア NAT (CGNAT: au / docomo / softbank の MAP-E など) は
    国内でも 1 公開 IP に数千端末ぶら下がっている。

方針:
  - 攻撃確度が "critical" (honeytoken 使用) でも、共有 IP の可能性が高い ASN
    では `managed_challenge` までに留め、永久 block はしない。
  - 純粋な VPS / クラウド ASN (Hetzner / DigitalOcean / OVH 等) は攻撃元と
    してメジャーで、かつエンドユーザの一般トラフィックは少ないので block 可。
  - 判定は ASN ベースで、ASN が取れなければ "保守的に challenge" を選ぶ。

決定マトリクス:
  ASN class       | block | challenge | managed_challenge
  ----------------|-------|-----------|-------------------
  vpn / tor       |   ×   |     ×     |       ◯  (常にこれ)
  mobile / cgnat  |   ×   |     ◯     |       ◯
  cloud / vps     |   ◯   |     ◯     |       ◯  (block 可)
  residential     |   ◯*  |     ◯     |       ◯  (高確度時のみ block)
  unknown         |   ×   |     ◯     |       ◯  (block しない)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── 既知 VPN / Tor / 匿名化サービスの ASN ──────────────────────────────
# 出典: 公開済 ASN whois + 各 VPN プロバイダ公表 IP プール。完全網羅は不可能だが、
# メジャー所をカバーすれば誤 ban の大半を防げる。
_VPN_TOR_ASNS: set[int] = {
    # Mullvad VPN
    39351,
    # Proton VPN (M247 / Tefincom が経由する場合あり、自社 ASN 含む)
    62371,
    # NordVPN (Tefincom 経由)
    9009,    # M247 (Nord / Surfshark 等が利用)
    # Surfshark
    202018,
    # Private Internet Access
    207990,
    # IPVanish (StackPath / Highwinds)
    33438,
    # ExpressVPN (Datacamp Limited)
    212238,
    # Windscribe
    51852,
    # CyberGhost
    198605,
    # Cloudflare WARP (1.1.1.1) — own ASN
    13335,
    # Tor 出口ノードは静的 IP リストで別 detect する (ASN 固定不可) が、
    # しばしば OVH / Hetzner / Online SAS 等の VPS ASN を経由する。
    # → 我々の方針では VPS ASN は block 可、ただし "tor exit list" にあれば
    #   override で managed_challenge に降格させる (後述)。
}

# モバイル / CGNAT (国内主要 + 海外大手)。共有 IP 度が極めて高い。
_MOBILE_CGNAT_ASNS: set[int] = {
    # 日本
    2516,   # KDDI au
    9605,   # NTT docomo
    17676,  # SoftBank Mobile
    4713,   # NTT OCN (CGNAT 増加中)
    # 海外メジャー
    7922,   # Comcast (一部 CGNAT)
    20057,  # AT&T Mobility
    21928,  # T-Mobile US
    12389,  # PJSC Rostelecom (大規模 CGNAT)
}

# VPS / クラウド (攻撃源として典型。エンドユーザは少ないので block 可)
_CLOUD_VPS_ASNS: set[int] = {
    16509,  # Amazon AWS
    14618,  # Amazon AWS (us-east-1 系)
    8075,   # Microsoft Azure
    15169,  # Google Cloud
    24940,  # Hetzner
    14061,  # DigitalOcean
    16276,  # OVH
    20473,  # Choopa / Vultr
    63949,  # Linode / Akamai
    16276,  # OVH SAS
    12876,  # Online SAS (Scaleway)
    9009,   # M247 (一部 cloud としても利用) — VPN 用途と重複
}


def classify_asn(asn: Optional[int]) -> str:
    """ASN を 'vpn_tor' / 'mobile_cgnat' / 'cloud_vps' / 'unknown' に分類。"""
    if asn is None:
        return "unknown"
    if asn in _VPN_TOR_ASNS:
        return "vpn_tor"
    if asn in _MOBILE_CGNAT_ASNS:
        return "mobile_cgnat"
    if asn in _CLOUD_VPS_ASNS:
        return "cloud_vps"
    return "unknown"


# ─── Tor 出口ノード判定 (best-effort) ────────────────────────────────────
# 公式リスト https://check.torproject.org/exit-addresses は数時間ごと更新。
# 起動時に env path から読めればロードし、なければ skip。
import os
import threading

_tor_exit_ips: set[str] = set()
_tor_exit_lock = threading.Lock()


def load_tor_exit_list_from_file(path: Optional[str] = None) -> int:
    """Tor exit list ファイルをロードする。フォーマット例:

        ExitNode <fingerprint>
        Published <ts>
        ExitAddress 1.2.3.4 <ts>

    1 ExitAddress 行から IP を抽出する。
    """
    path = path or os.environ.get("SS_TOR_EXIT_LIST_PATH", "")
    if not path or not os.path.isfile(path):
        return 0
    ips: set[str] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("ExitAddress "):
                    parts = line.split()
                    if len(parts) >= 2:
                        ips.add(parts[1].strip())
    except Exception as exc:
        logger.warning("[cf_ban_policy] tor exit list load failed: %s", exc)
        return 0
    with _tor_exit_lock:
        _tor_exit_ips.clear()
        _tor_exit_ips.update(ips)
    logger.info("[cf_ban_policy] loaded %d Tor exit IPs", len(ips))
    return len(ips)


def is_tor_exit(ip: Optional[str]) -> bool:
    if not ip:
        return False
    with _tor_exit_lock:
        return ip in _tor_exit_ips


# ─── 最終判断: どの mode で CF に送るか ────────────────────────────────
def decide_cf_mode(
    *,
    ip: Optional[str],
    asn: Optional[int],
    confidence: str,
) -> str:
    """Cloudflare access_rules の `mode` 値を返す。

    confidence:
        - "low":      managed_challenge 固定 (canary パターン軽微等)
        - "medium":   通常パスで unknown は challenge、cloud_vps は block
        - "critical": honeytoken 使用等。block の最大確度。

    返り値: "block" / "challenge" / "managed_challenge" / "whitelist"
        "whitelist" = 一切何もしない (loopback / 自社等)
    """
    if not ip or ip in ("127.0.0.1", "::1"):
        return "whitelist"

    # Tor 出口は確度に関係なく絶対に block しない (managed_challenge まで)
    if is_tor_exit(ip):
        return "managed_challenge"

    cls = classify_asn(asn)

    if cls == "vpn_tor":
        # VPN 共有出口は永久 block 絶対 NG。CAPTCHA で個別フィルタ。
        return "managed_challenge"

    if cls == "mobile_cgnat":
        # CGNAT は 1 IP 数千ユーザ。confidence が critical でも block 不可。
        # challenge で個別判定させる。
        return "challenge"

    if cls == "cloud_vps":
        # クラウド / VPS は攻撃源として典型、エンドユーザ少。
        if confidence in ("critical", "medium"):
            return "block"
        return "challenge"

    # unknown ASN: ASN が取れなかった or 分類外。
    # 保守的に: critical でも block しない。challenge までに留めて誤 ban 回避。
    if confidence == "critical":
        return "challenge"
    return "managed_challenge"
