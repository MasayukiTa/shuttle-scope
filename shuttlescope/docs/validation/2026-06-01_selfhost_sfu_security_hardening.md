# 自宅 self-host SFU(LiveKit) のセキュリティ対策 runbook (2026-06-01)

自宅で SFU を立てる以上、SFU は inbound 到達が必要＝**ポート開放が必須**。
事故を防ぐための対策を、重要度順に。前提: GPU 機(PRO 6000)・DB・動画は**最重要資産**。

## 0. 大原則（最重要）— ネットワーク分離（DMZ）
- **GPU/データ機(PRO 6000, DB, videos) は絶対に port-forward しない**。
- **SFU は別ホスト/別 VLAN(DMZ) に隔離**し、そこだけポート開放する。
- **CV worker(GPU 機) は SFU へ "outbound" で接続**（room subscribe）。GPU 機への inbound は一切開けない。
  → 万一 SFU が侵害されても、攻撃者は内部 LAN(DB/動画/SSH)へ横移動できない。
- SFU ホストから内部 LAN への通信は **CV worker が使う最小ポートのみ許可**（egress も絞る）。

## 1. 開けるポートを最小化
LiveKit が要するもの**だけ**を、SFU ホストの内部 IP 宛に forward：
- WSS シグナリング: TCP 443(or 7880) — **TLS 必須**
- WebRTC メディア: **UDP の単一ポート**に固定推奨（`rtc.udp_port`、例 7882）。広い UDP レンジ開放は避ける
- TCP フォールバック/TURN: TCP 7881（必要時のみ）
- 上記以外は**全て drop**。ルーターの **UPnP を無効化**（勝手にポートが開くのを防止）。

## 2. TLS / 認証ゲート
- **WSS / TURNS を TLS 化**（Let's Encrypt）。平文 ws/turn は使わない。
- **LiveKit は JWT(access token) を持つクライアントしか room に入れない**。token は ShuttleScope backend が
  **認証済みユーザにのみ発行**（Phase 2: `POST /api/media/token` を get_auth でゲート、operator grant は
  privileged role 限定）。→ インターネットのスキャナは token を得られず join 不可。
- **API secret を厳重管理**（環境変数のみ、リポジトリに置かない）。**token TTL は短く**（例 1h、`SS_LIVEKIT_TOKEN_TTL`）。
- 定期的に **API key/secret をローテーション**。

## 3. ホスト・ファイアウォール・実行権限
- SFU ホストの host firewall(ufw 等) で **開けたポート以外 inbound drop**。
- LiveKit を **コンテナ + 非 root** で実行、最小権限。イメージは公式・**常時最新**（CVE 追従）。
- SSH/RDP/管理は **Cloudflare Access(Zero Trust) のまま**（公開しない）。SFU ホストの SSH も鍵のみ・公開しない。
- fail2ban / 接続レート制限を signaling ポートに。

## 4. 濫用・DoS 対策
- LiveKit 側で **room 数 / 参加者数 / 帯域 / 接続レートの上限**を設定。
- token に **room を限定**（`video.room` 固定）＝1 token で他 room に入れない（実装済み: room_name_for）。
- **DDoS は自宅公開の本質的リスク**。100Mbps 回線は飽和させられ得る。緩和: ルーター/ISP の防御、
  接続元レート制限、監視＋自動遮断。**本番規模では DC/クラウド + 上流 DDoS 防御が安全**（自宅公開は実験/小規模向け）。

## 5. 監視・運用
- 接続ログ・異常検知（未知 IP の大量接続、token 失敗多発）をアラート化。
- 定期的に **公開ポートを外部からスキャン**して「意図したポートだけ」開いていることを確認。
- インシデント時の手順: ポート閉鎖 → SFU 停止 → token secret ローテーション → ログ精査。

## 6. まとめ（事故を防ぐ最小セット）
1. **DMZ 分離**（GPU/DB 機は port-forward しない・SFU 別ホスト）← 最重要
2. **最小ポート + UPnP 無効 + host firewall drop**
3. **TLS + 認証済みユーザのみ token 発行 + 短 TTL + secret 厳重管理**
4. **上限設定 + 監視 + 定期スキャン**
5. 本番規模化時は **DC/クラウド + 上流 DDoS 防御**へ移行（自宅公開は小規模に留める）
