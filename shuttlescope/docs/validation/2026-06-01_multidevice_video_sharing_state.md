# 複数台 iOS/Android 映像共有 — 統合状態 & 検証 runbook (2026-06-01)

散在する 11 個の remote-camera gap spec (private_docs) と成熟した実装を 1 枚に統合し、
**実機が来たら即検証できる runbook** にする。結論: **実装はほぼ feature-complete**。
残りは「実機検証」と「ライブ運用 UX」であり、新規コードではない。

## 1. アーキテクチャ (3 層分離)
| 層 | 役割 | 実装 |
|---|---|---|
| Exposure | リモート到達 (HTTPS/URL/API) | `backend/routers/tunnel.py` provider-aware (cloudflare / ngrok / auto) |
| Signaling/Control | セッション・デバイス・SDP/ICE 交換 | `backend/ws/camera.py` `/ws/camera/{session_code}` (operator/devices/viewers) |
| Media | 実映像 (低遅延) | ブラウザ WebRTC (`getUserMedia`) — 専用アプリ不要 |
- iOS Safari の getUserMedia は **secure context (HTTPS) 必須** → リモートは tunnel 経由 HTTPS が前提。
- **TURN なし = best effort**（社内/VPN/strict NAT/モバイルで直 P2P は失敗しやすい）。正直に「TURN required for stable remote video」と表示する方針。

## 2. 実装済み (Phase A–E 完了)
- tunnel provider 選択 (cloudflare/ngrok/auto) + 健全性チェック
- sender / receiver / viewer の WebRTC フロー、ICE/TURN config 配信 + 診断
- reconnect 改善、stale active-camera 解放、guided handoff、grouped device manager
- Annotator のリモート health バナー + provider ラベル
- フロント: `CameraSenderPage.tsx`(送信), `DeviceManagerPanel.tsx`, `useDeviceHeartbeat.ts`

## 3. シグナリングの堅牢化済みガード (`backend/ws/camera.py`)
| 項目 | 値 |
|---|---|
| MAX_DEVICES_PER_SESSION | 10 |
| MAX_VIEWERS_PER_SESSION | 30 |
| MAX_TOTAL_CAMERA_SESSIONS | 100 |
| MAX_TOTAL_CAMERA_CONNECTIONS | 500 |
| msg size cap | 64 KB (巨大 frame DoS 遮断) |
| rate limit | 60 msg/s |
| operator owner 整合 | session_code 単位で先着 user_id のみ復帰可 (code 4403) |
| 排他 | per-session asyncio.Lock、empty 時 GC |
超過時は code 1013 で close。複数台同時接続の構造的安全性は確保済み。

## 4. 既存テスト coverage (`backend/tests/`)
- `test_websocket_signaling.py` (15): operator/device/viewer 接続、device_list_update、**2台同時**、viewer joined/left、relay 双方向、manager unit。
- `test_device_lifecycle.py`, `test_camera_operator_owner.py`: ライフサイクル / owner 整合。
- **未カバー (実機/模擬両方)**: 3台以上同時、cap 到達時の close、handoff 競合、reconnect storm、TURN フォールバック表示。
  → これらは threading-WS テストが CI でフレーキー (本ファイルに timeout skip 多数) のため、**実機検証側で確認するのが安全**。

## 5. 実機検証 runbook (デバイス入手後に即実行)
前提: tunnel(ngrok 推奨, 社内環境) 起動 + session code/password 発行。
1. **iPhone Safari sender**: 共有 URL → code+password → カメラ許可 → 映像送信。operator に device 出現。
2. **2台目 (Android Chrome) sender**: 同時接続 → grouped device manager に2台。
3. **3台目** → MAX(10) 未満で全員 list 反映、operator が任意ソース選択。
4. **operator PC viewer**: 映像受信。**tablet viewer**: 受信。
5. **TURN-backed path**: TURN 有効化 → strict NAT/モバイル回線で接続安定を確認。無効時は「best effort」表示が出るか。
6. **handoff**: active camera を別デバイスへ委譲、ダイアログが理解可能か。
7. **reconnect/stale**: 1台を機内モード→復帰、stale 警告と再要求文言を確認。
合格ゲート: 外部 sender / 外部 viewer / tablet viewer / TURN path / grouped manager のライブ可読性、の5点 (FINAL_VALIDATION_GAPS 準拠)。

## 6. 正直な現状
- コード実装は remote camera/viewer フローで **feature-complete に近い**。
- 残リスクは **実機検証とライブ運用 UX** が主。新規実装ではない。
- 「works anywhere / guaranteed remote video」とは謳わない。**TURN 検証完了までは experimental 表記**。

## 7. 次アクション (環境/デバイス復帰後)
1. 上記 runbook を iPhone+Android+tablet+PC で実走 → 不具合のみ最小修正。
2. TURN-backed の安定性を社内/モバイルで確認 → 安定なら "experimental" を外す。
3. 必要なら 3台以上の模擬テストを **検証可能な環境で** 追加 (CI フレーキー回避のため非 threading な manager-unit 形式で)。
