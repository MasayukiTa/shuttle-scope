# メディア配置トポロジ — 3ホスト分離 (2026-06-01)

ユーザー所有機材での具体配置。設計: `2026-06-01_rtmp_sfu_media_plane_design.md`、
セキュリティ: `2026-06-01_selfhost_sfu_security_hardening.md` の DMZ 分離をこの機材に落とす。

## ホスト割当
| ホスト | 役割 | 外部公開 |
|---|---|---|
| **GMKtec K10** (i9-13900HK/64GB) | **DMZ: SFU(LiveKit) 専用・外向き** | **ここだけ** port-forward |
| **HP Z8 G4** (RTX PRO 6000 Max-Q 予定) | CV 推論 + **動画 HDD 保存** | **非公開**。CV worker は SFU へ outbound のみ |
| Minisforum X1 AI | ShuttleScope 制御面 (API / Cloudflare Access) | Cloudflare Access のみ |
- 全機 **2.5GbE 有線 LAN**。内部転送 ~250MB/s（SFU↔GPU↔ストレージに潤沢）。

## データフロー
```
[venue] Mavic(RTMP)/iOS(WebRTC) ──internet──▶ GMKtec(LiveKit SFU)  ← port-forward はここだけ
                                                   │ (2.5GbE LAN, 内部)
                          Z8 CV worker ──outbound subscribe──┘ → frame → PRO6000 で CV → 要約
                                                   └─ 録画(egress/worker) ──2.5GbE──▶ Z8 HDD
[視聴] 要約/結果 ──Cloudflare WSS──▶ 多数（軽量）
       動画視聴(多数) ──LL-HLS + CDN──▶ ファンアウト（自宅上り回避）
       低遅延動画(少数) ──WebRTC(WHEP)──▶
ShuttleScope 制御面(X1 AI): /api/media/token 発行・session 管理（Cloudflare 経由）
```

## セキュリティ必須事項（事故防止の肝）
1. **VLAN/サブネット分離**: GMKtec を別セグメント。GMKtec→Z8 は**メディアの特定ポートのみ**許可、
   Z8 の SSH/DB/管理面へは到達不可。GMKtec 侵害時も Z8 の動画/データへ横移動不可。
2. **Z8 は internet inbound ゼロ**。port-forward は **GMKtec の IP だけ**（Z8/X1 は forward 禁止）。
3. GMKtec: 最小ポート(WSS + 単一 UDP メディアポート + 必要なら TCP7881) のみ、host firewall で他 drop、UPnP 無効、
   LiveKit はコンテナ非 root・常時最新、TLS、token ゲート（認証済みのみ・実装済 `/api/media/token`）。
4. 動画は Z8 HDD（最重要資産）。バックアップ（外付け SSD/NAS）を別途。

## 帯域の現実（重要）
- **2.5GbE は内部のみ**。外部は **自宅 ISP 回線が律速**。
- **ingest**（カメラ→GMKtec）= 自宅**下り**。**distribution**（視聴←GMKtec）= 自宅**上り**（多くの家庭で下りより細い）。
- → **多数の動画視聴を WebRTC で自宅から配るのは上り不足**。**LL-HLS + CDN にオフロード**し、WebRTC は
  「送信 + 低遅延が要る少数」に限定。Cloudflare 100Mbps はメディア非経由なので無関係（制御面のみ CF）。
- GMKtec(K10) は中規模 SFU 可。200送信/400視聴フルは単一ノード限界 → LiveKit 水平スケール（後段）。

## 段階
1. ✅ token 認証ゲート（実装済 `/api/media/token`）
2. GMKtec に LiveKit デプロイ（コンテナ）+ TLS + 最小ポート port-forward + VLAN
3. Z8 CV worker を room subscriber 化 → 既存 CV パイプライン + Z8 HDD 録画
4. Mavic RTMP Ingress（GMKtec の LiveKit ingress）
5. 視聴 = LL-HLS+CDN（多数）/ WHEP（少数低遅延）
