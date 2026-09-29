# Electron + DRM 動画の取り扱い

ShuttleScope では「DRM 復号は一切しない」が大前提。あらゆる経路で Widevine
CDM bypass / HDCP 解除 / ライセンス回避は実装しない。

このドキュメントは「DRM 保護コンテンツに正規ライセンスでアクセスする視聴者が、
分析用の手元コピーを残したい」というユースケースについて、3 つある経路と
それぞれの限界を整理する。

---

## 経路 1: yt-dlp による HLS / DASH ダウンロード (DRM 検知で blocked)

**実装場所**: `backend/utils/video_downloader.py` + `StreamingDownloadPanel.tsx`

- `yt-dlp` が直接ダウンロードできるサイトはこれが第一候補。
- DRM が掛かっている場合 yt-dlp は `--allow-unplayable-formats` を付けない限り
  `403 Forbidden` または `ERROR: This video is DRM protected` で停止する。
  ShuttleScope は意図的にこのフラグを **付けない**。
- 会員限定サイトは以下の順で試す:
  1. ブラウザの `cookies.txt` を投入 (Cookie-Editor 等で書き出し)
  2. パスワード保護動画は「動画パスワード」フィールドに入力
     (yt-dlp の `--video-password` 相当、Vimeo Showcase 等で利用)
  3. それでも DRM 検知される場合 → 経路 2 を試す

## 経路 2: Electron WebView 経由視聴 + OS-level 画面録画

**実装場所**: `electron/main.ts` (`screen-capture-start` IPC) + `WebViewPlayer.tsx`

- ユーザが正規アカウントでログインして再生 → OS のフレームバッファを
  `desktopCapturer` で録画。これは **OBS と同等の合法経路**。
- Widevine **L3 (ソフトウェア CDM)** は Electron 標準ビルドに同梱されているため
  ブラウザでログインして見られるサイトはたいてい再生できる。
- `partition="persist:streaming"` でセッション Cookie が永続化される。
- 録画品質は `low (1.5Mbps/480p) / med (5Mbps/720p, 既定) / high (9Mbps/1080p)`
  をフロントの dropdown で切替可能。
- ナビゲーション安全装置: `psl` ベースの registrable domain 一致のみ許可。
  embedded credentials / 内部 IP / 非 HTTPS は SSRF ガードで拒否。
- HDCP black-frame 検出: 録画後 `ffmpeg blackdetect` で黒フレーム比率を計測し、
  80% 以上が黒なら警告を出す (UI に通知)。

### 経路 2 の限界

Widevine **L1 (ハードウェア CDM)** が必須なサイトはこの経路でも視聴できない。
代表例:
- Netflix (HD 以上)
- DAZN の 1080p+ ストリーム
- U-NEXT の HD コンテンツ

これらは Electron 標準の SW CDM では再生フェーズで失敗するか、再生に成功しても
HDCP が画面キャプチャに対して黒フレームを返す。

## 経路 3: castLabs Electron への切替 (上級者向け、難易度 L)

**現状**: ShuttleScope は標準 `electron@^39` を使用。castLabs 版への自動切替はしない。

castLabs の Electron は VMP (Verified Media Path) 署名済みで Widevine L1
ライセンスサーバから L1 鍵を受け取れる。だが、これを ShuttleScope に組み込むかは
要検討事項:

### メリット
- L1 必須サイトでも再生自体は可能になる。

### デメリット / 制約
- **L1 鍵があっても HDCP black-frame 問題は解決しない**。OS-level 画面録画を
  検出すると配信側がフレームバッファを黒で塗りつぶす (これはプラットフォーム
  動作であり、castLabs もこれを bypass しない)。
- 結果として「再生はできるが録画は黒画面」になり、ShuttleScope の本来用途
  (分析用コピー作成) は達成されない。
- castLabs 版は配布バイナリのサイズが大きい / リリース頻度が遅い / バージョン
  選定が標準 Electron と非同期。
- **法的グレーゾーン**: Widevine L1 ライセンスサーバとの直接通信は配信
  サービスの ToS に抵触する可能性が高く、組織として推奨できない。

### もし castLabs 版を試したい場合 (個人ユース、自己責任)

```jsonc
// shuttlescope/package.json
{
  "devDependencies": {
    "electron": "github:castlabs/electron-releases#v39.0.0+wvcus"
  }
}
```

利用可能バージョン: https://github.com/castlabs/electron-releases/releases

- 現在の `electron@^39.8.5` と完全一致する castLabs リリースが無い場合、
  最も近いマイナーバージョンに合わせて `package-lock.json` を再生成すること。
- 切り替え後 `npm install` で github tarball を取得 → `npm run build` で動作確認。
- Widevine VMP 署名は castLabs が提供する EVS (Electron Verification Service) を
  経由して取得する必要がある (公式手順参照)。
- 上記いずれかが面倒な場合、結論として **「経路 2 で見えるものを録る」** に
  集中するのが最も生産的。

---

## まとめ (どの経路を選ぶか)

| サイト種別                  | 第一候補 | 第二候補 | 備考 |
|-----------------------------|----------|----------|------|
| YouTube / Twitter / niconico | 経路 1   | 経路 2   | yt-dlp で DL 可能 |
| Twitch メンバー / Vimeo     | 経路 1 + cookies.txt | 経路 2 | Vimeo Showcase は video_password も併用 |
| YouTube Live (DRM 検知)     | 経路 2   | -        | live-from-start 失敗時に screen capture |
| DAZN / WOWOW / U-NEXT (SD)  | 経路 2   | -        | L3 で再生できる解像度のみ |
| Netflix / DAZN HD+ (L1)     | 録画不可 | -        | castLabs 版でも HDCP で黒画面 |

ShuttleScope の標準ビルドは経路 1 + 2 のみをサポートする。経路 3 は本リポジトリに
コミットせず、必要なユーザが自身の手元で `package.json` を差し替える前提。
