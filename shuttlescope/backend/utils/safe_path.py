"""パストラバーサル対策ユーティリティ + SSRF 防御ヘルパー"""
from pathlib import Path
from fastapi import HTTPException


def safe_path(base_dir: str | Path, user_input: str | Path) -> Path:
    """user_input を base_dir 配下に限定して解決する。

    base_dir の外を指す場合は 403 を返す。
    シンボリックリンクは resolve() で展開してから検証する。
    """
    base = Path(base_dir).resolve()
    target = (base / user_input).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="指定パスはベースディレクトリ外です")
    return target


def validate_external_url(url: str, *, field_name: str = "url") -> str:
    """外部動画 URL / webhook URL の SSRF 対策バリデータ。

    以下を拒否する:
      - http/https 以外のスキーム (file://, ftp://, gopher://, data://, javascript:)
      - localhost / 127.0.0.0/8 / ::1 / fe80::/10 / fc00::/7
      - プライベート IP (10/8, 172.16/12, 192.168/16, 169.254/16 AWS meta)
      - 短縮記法 (127.1, 0x7f000001, 2130706433)
      - IPv4-mapped IPv6 (::ffff:127.0.0.1)
      - メタデータホスト (metadata.google.internal, metadata.aws.amazon.com)
      - `.local` / `.internal` / 空 host

    yt-dlp や webhook 送信等、サーバ側で URL を fetch する箇所で呼ぶ。
    """
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=422, detail=f"{field_name} must be a non-empty string")
    url = url.strip()

    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=422, detail=f"{field_name}: invalid URL")

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail=f"{field_name}: only http/https allowed")

    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=422, detail=f"{field_name}: missing host")

    # 既知の危険ホスト名
    blocked_names = {
        "localhost", "metadata.google.internal", "metadata.aws.amazon.com",
        "169.254.169.254", "169.254.170.2",  # AWS/GCP metadata
    }
    if host in blocked_names or host.endswith(".local") or host.endswith(".internal"):
        raise HTTPException(status_code=422, detail=f"{field_name}: blocked host")

    # IP アドレスとして解釈可能か (短縮 / hex / decimal もここで正規化される)
    import ipaddress, socket
    ip_candidates = [host]
    # ホスト名を DNS 解決して IP も検証
    try:
        resolved = {a[4][0] for a in socket.getaddrinfo(host, None)}
        ip_candidates.extend(resolved)
    except socket.gaierror:
        # DNS 解決失敗 → host 名だけ検証
        pass

    for ip_str in ip_candidates:
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        # ループバック / プライベート / リンクローカル / multicast / reserved を全拒否
        if (
            addr.is_loopback or addr.is_private or addr.is_link_local or
            addr.is_multicast or addr.is_reserved or addr.is_unspecified
        ):
            raise HTTPException(
                status_code=422,
                detail=f"{field_name}: private / loopback / link-local IP is not allowed",
            )
        # IPv4-mapped IPv6 もチェック
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            mapped = addr.ipv4_mapped
            if mapped.is_loopback or mapped.is_private or mapped.is_link_local:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name}: IPv4-mapped private IP is not allowed",
                )

    return url
