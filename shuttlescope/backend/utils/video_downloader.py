"""動画ダウンロード（yt-dlpラッパー）

任意の配信URL（YouTube, Twitter, Bilibili, ニコニコ等）を yt-dlp でダウンロードする。
ログイン必須サイトは cookie_browser でブラウザを指定すると
そのブラウザの Cookie を自動取得して認証を通過できる。

完了後は localfile:// 形式の絶対URLを返すため、
Electron のカスタムプロトコルでそのまま再生可能。
"""
import asyncio
import os
import uuid
from pathlib import Path


try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

# yt-dlp が対応しているブラウザ名
SUPPORTED_BROWSERS = {"chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "safari"}


class VideoDownloader:

    def __init__(self):
        # cwd は Electron が appPath を設定済みなので相対パスで解決できる
        self.download_dir = Path(os.path.abspath("./videos"))
        self.download_dir.mkdir(exist_ok=True)
        self.active_downloads: dict[str, dict] = {}

    def create_job_id(self) -> str:
        return str(uuid.uuid4())

    async def start_download(
        self,
        url: str,
        job_id: str,
        quality: str = "720",
        cookie_browser: str = "",
    ) -> None:
        """非同期でダウンロードを開始。進捗は job_id で管理。

        Args:
            url:            ダウンロード対象URL
            job_id:         進捗管理用UUID
            quality:        "360" / "480" / "720" / "1080" / "best"
            cookie_browser: 使用するブラウザ名（"" = Cookie不使用）
                            "chrome" / "edge" / "firefox" / "brave" /
                            "opera" / "vivaldi" / "chromium" / "safari"
        """
        if not YT_DLP_AVAILABLE:
            self.active_downloads[job_id] = {
                "status": "error",
                "error": "yt-dlp がインストールされていません（pip install yt-dlp）",
            }
            return

        self.active_downloads[job_id] = {"status": "pending"}

        # 画質に応じた format 指定
        # YouTube は映像と音声が別ストリームなので bestvideo+bestaudio でマージ
        height = quality if quality != "best" else "2160"
        fmt = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}]+bestaudio"
            f"/best[height<={height}]"
            "/best"
        )

        yt_opts: dict = {
            "outtmpl": str(self.download_dir / f"{job_id}.%(ext)s"),
            "format": fmt,
            "merge_output_format": "mp4",
            "progress_hooks": [lambda d: self._update_progress(job_id, d)],
            "quiet": True,
            "no_warnings": True,
        }

        # ── Cookie 設定 ──────────────────────────────────────────────────────
        # ログイン必須サイトでは指定したブラウザの Cookie を自動取得する
        # yt-dlp が対応していないブラウザ名はスキップ（エラー防止）
        browser = cookie_browser.strip().lower()
        if browser and browser in SUPPORTED_BROWSERS:
            # (ブラウザ名, プロファイル, キーリング, コンテナ) の形式
            yt_opts["cookiesfrombrowser"] = (browser,)

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._download_sync(url, yt_opts, job_id)
            )
        except Exception as e:
            self.active_downloads[job_id] = {
                "status": "error",
                "error": self._format_error(str(e)),
            }

    # ── 内部メソッド ──────────────────────────────────────────────────────────

    def _download_sync(self, url: str, yt_opts: dict, job_id: str) -> None:
        """同期ダウンロード本体（run_in_executor で別スレッド実行）"""
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])

        # yt-dlp が "finished" フックを発火する時点はマージ前の場合がある。
        # ydl.download() 完了後にファイルを glob 検索して確実に完了パスを取得。
        output_files = sorted(
            f for f in self.download_dir.glob(f"{job_id}.*")
            if f.suffix not in {".part", ".ytdl", ".tmp"}
        )
        if output_files:
            abs_path = str(output_files[0].resolve())
            # Windows パスのバックスラッシュを変換して localfile:// URL を生成
            localfile_url = "localfile:///" + abs_path.replace("\\", "/")
            self.active_downloads[job_id] = {
                "status": "complete",
                "filepath": localfile_url,
            }
        else:
            self.active_downloads[job_id] = {
                "status": "error",
                "error": "ダウンロード後に出力ファイルが見つかりません",
            }

    def _update_progress(self, job_id: str, d: dict) -> None:
        """yt-dlp 進捗フック"""
        if d["status"] == "downloading":
            self.active_downloads[job_id] = {
                "status": "downloading",
                "percent": d.get("_percent_str", "0%").strip(),
                "speed": d.get("_speed_str", "").strip(),
                "eta": d.get("_eta_str", "").strip(),
            }
        elif d["status"] == "finished":
            # 個別ストリームのダウンロード完了（マージ処理がある場合はまだ続く）
            self.active_downloads[job_id] = {
                "status": "processing",
                "percent": "100%",
                "speed": "",
                "eta": "",
            }

    @staticmethod
    def _format_error(raw: str) -> str:
        """yt-dlp のエラーメッセージを日本語で補足する"""
        msg = raw

        if "cookiesfrombrowser" in raw or "cookies" in raw.lower():
            if "locked" in raw.lower() or "database" in raw.lower():
                msg = (
                    "Cookieの読み取りに失敗しました。\n"
                    "対象ブラウザが起動中の場合は閉じてから再試行してください。\n"
                    f"（詳細: {raw}）"
                )
            elif "not installed" in raw.lower() or "not found" in raw.lower():
                msg = (
                    "指定したブラウザが見つかりません。\n"
                    "ブラウザがインストールされているか確認してください。\n"
                    f"（詳細: {raw}）"
                )
            else:
                msg = f"Cookie取得エラー: {raw}"

        elif "HTTP Error 403" in raw or "Private video" in raw:
            msg = (
                "アクセスが拒否されました（403）。\n"
                "ログイン済みのブラウザのCookieを指定するか、"
                "動画が公開されているか確認してください。"
            )
        elif "HTTP Error 404" in raw or "not available" in raw.lower():
            msg = "動画が見つかりません（404）。URLを確認してください。"
        elif "This video is not available" in raw:
            msg = "この動画はご利用の地域では視聴できません（地域制限）。"
        elif "Sign in" in raw or "login" in raw.lower():
            msg = (
                "ログインが必要な動画です。\n"
                "「Cookieブラウザ」でログイン済みのブラウザを選択してください。"
            )
        elif "DRM" in raw or "Widevine" in raw or "drm" in raw.lower():
            msg = (
                "DRM保護されたコンテンツはダウンロードできません。\n"
                "埋め込みブラウザ（WebView）での視聴機能を使用してください。"
            )

        return msg

    def get_progress(self, job_id: str) -> dict:
        """ダウンロード進捗を取得"""
        return self.active_downloads.get(job_id, {"status": "unknown"})


# シングルトン
video_downloader = VideoDownloader()
