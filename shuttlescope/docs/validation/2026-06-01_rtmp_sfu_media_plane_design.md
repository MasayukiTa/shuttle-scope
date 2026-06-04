# RTMP + SFU メディアプレーン再設計 (2026-06-01)

100試合 / 200 iOS 送信 / 400 視聴 規模に耐えるため、現行の **P2P WebRTC signaling
(`backend/ws/camera.py`, caps 10/30/500)** を **SFU ベース**へ作り替える。
媒体バックボーンは **LiveKit**（OSS: RTMP ingress + WebRTC SFU + HLS egress を一式）。

## 1. 制御面 / メディア面の分離（Cloudflare 100Mbps 回避の核）
- **Cloudflare Tunnel は HTTP(S) のみ**。WebRTC(SRTP/UDP)・RTMP(TCP)・HLS-origin の**メディアは CF を経由させない**。
  → 100Mbps 制限はメディアに掛からない。CF は制御面（ページ/WSS シグナリング/API/トークン発行）だけ＝極小帯域。
- **メディア面 = SFU(LiveKit) の直 IP・直帯域**。自宅から直出しするには SFU が公開到達 IP を要するため、
  **SFU は公開 IP のホスト/クラウドに配置**（自宅 GPU=PRO 6000 は CV 処理に専念）。ポート開放を避けたい要件と
  大規模を両立させるには SFU を自宅外に出すのが自然。
- HLS を配るなら **CF プロキシ経由にしない**（CF 無料は大量動画配信を ToS で制限）。SFU/別 CDN から直配信。

## 2. トポロジ
```
Mavic 4 Pro ──RTMP──▶ LiveKit Ingress ─┐
iOS(WHIP) / USB ─WebRTC──▶  LiveKit room ├─▶ CV worker(PRO6000): room subscribe → frame → YOLO/TrackNet → 要約/アシスト
視聴 ─WHEP(WebRTC) / HLS egress(+CDN)────┘
ShuttleScope backend: access-token 発行 + match↔room マッピング + ロール→grant（operator 制御）
Cloudflare: token/API/ページのみ（メディア非経由）
```

## 3. 役割 → LiveKit grant マッピング（既存 camera.py のロール意味を継承）
| ShuttleScope ロール | LiveKit grant |
|---|---|
| operator | roomJoin + canPublish + canSubscribe + canPublishData（制御権） |
| camera (iOS/USB/Mavic ingress) | roomJoin + canPublish（送信のみ） |
| viewer (PC/tablet) | roomJoin + canSubscribe（受信のみ。phone は既定 video 無し＝subscribe しない/要約のみ） |

## 4. スケール指針（PRO 6000 Max-Q 96GB 前提）
- **GPU が律速**（200 同時 realtime は 1枚でも不足）。低fps(要約統計なら 5–10fps)＋frame バッチ集約＋軽量モデルで stream/GPU を稼ぐ。96GB を活かし複数モデル常駐・大バッチ。
- **視聴 400 は LL-HLS egress + CDN にオフロード**（WebRTC は送信＋低遅延が要る少数に限定）。
- TURN は LiveKit に内蔵（自前 coturn クラスタ or LiveKit 同梱）。

## 5. 実装フェーズ（段階導入。現行 camera.py は当面温存）
- **Phase 1 (本コミット)**: backend に LiveKit 統合層 = **access-token 発行 + match→room 名 + ロール→grant**。
  LiveKit サーバ無しで JWT を生成・検証する単体テスト可能。env: `LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET`。
- Phase 2: token 発行 API エンドポイント（`POST /api/media/token`）+ フロントの WHIP/WHEP クライアント差し替え。
- Phase 3: LiveKit Ingress(RTMP) 設定 + Mavic 配信ガイド。
- Phase 4: CV worker を LiveKit room subscriber 化（frame 取得→既存パイプライン）。
- Phase 5: HLS egress + CDN、TURN クラスタ、水平スケール、現行 camera.py 置換/撤去。

## 6. 注意
- 大規模 SFU/GPU/帯域は **クラウド/DC コスト前提**。自宅・無料・ポート開放なしは「制御面のみ」。メディア面は別。
- LiveKit サーバ本体は**デプロイ案件**（self-host on 公開IPホスト or LiveKit Cloud）。コードは統合層から先行実装。
