"""動画ダウンロード（yt-dlpラッパー）

任意の配信URL（YouTube, Twitter, Bilibili, ニコニコ等）を yt-dlp でダウンロードする。
ログイン必須サイトは cookie_browser でブラウザを指定すると
そのブラウザの Cookie を自動取得して認証を通過できる。

完了後は localfile:// 形式の絶対URLを返すため、
Electron のカスタムプロトコルでそのまま再生可能。

【ffmpeg について】
映像と音声を別ストリームで配信するサービス（YouTube等）は
高画質ダウンロードに ffmpeg が必要。
ffmpeg が未インストールの場合は自動的に「プリマージ済みストリーム」
形式にフォールバックするが、画質が制限される場合がある。
"""
import asyncio
import os
import shutil
import uuid
from pathlib import Path


try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

# yt-dlp が対応しているブラウザ名
SUPPORTED_BROWSERS = {"chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "safari"}


def _check_ffmpeg() -> bool:
    """ffmpegがPATH上に存在するか確認する"""
    return shutil.which("ffmpeg") is not None


class VideoDownloader:

    def __init__(self):
        # cwd は Electron が appPath を設定済みなので相対パスで解決できる
        self.download_dir = Path(os.path.abspath("./videos"))
        self.download_dir.mkdir(exist_ok=True)
        self.active_downloads: dict[str, dict] = {}
        # ffmpeg 可用性をインスタンス生成時に一度だけ確認する
        self.ffmpeg_available: bool = _check_ffmpeg()

    def create_job_id(self) -> str:
        return str(uuid.uuid4())

    def get_capabilities(self) -> dict:
        """ダウンローダーの動作環境を返す（フロントエンド向け）"""
        return {
            "yt_dlp": YT_DLP_AVAILABLE,
            "ffmpeg": self.ffmpeg_available,
        }

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

        self.active_downloads[job_id] = {
            "status": "pending",
            "ffmpeg_available": self.ffmpeg_available,
        }

        height = quality if quality != "best" else "2160"

        if self.ffmpeg_available:
            # ffmpegあり: 映像・音声を別ストリームでダウンロードしてマージ（高画質）
            fmt = (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={height}]+bestaudio"
                f"/best[height<={height}]"
                "/best"
            )
        else:
            # ffmpegなし: プリマージ済みストリームのみ（画質が制限される場合あり）
            # bestvideo+bestaudio 形式を使うと ffmpeg 必須エラーになるため使わない
            fmt = (
                f"best[height<={height}][ext=mp4]"
                f"/best[height<={height}]"
                "/best"
            )

        yt_opts: dict = {
            "outtmpl": str(self.download_dir / f"{job_id}.%(ext)s"),
            "format": fmt,
            "progress_hooks": [lambda d: self._update_progress(job_id, d)],
            "quiet": True,
            "no_warnings": True,
        }

        # ffmpeg がある場合のみ merge_output_format を指定
        # （指定すると ffmpeg がない環境で強制マージが走りエラーになる）
        if self.ffmpeg_available:
            yt_opts["merge_output_format"] = "mp4"

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

        # ── ffmpeg 関連 ──────────────────────────────────────────────────────
        if "ffmpeg" in raw.lower() and (
            "not installed" in raw.lower()
            or "not found" in raw.lower()
            or "merging" in raw.lower()
        ):
            msg = (
                "ffmpegがインストールされていません。\n"
                "高画質ダウンロード（映像+音声のマージ）にはffmpegが必要です。\n"
                "【インストール方法】\n"
                "  Windows: https://ffmpeg.org/download.html からダウンロードし、\n"
                "  展開したbinフォルダをシステムのPATHに追加してください。\n"
                "  または winget install ffmpeg でもインストールできます。\n"
                "インストール後はアプリを再起動してください。\n"
                f"（詳細: {raw}）"
            )

        # ── Cookie 関連 ──────────────────────────────────────────────────────
        elif (
            "cookiesfrombrowser" in raw
            or "cookies" in raw.lower()
            or "cookie" in raw.lower()
        ):
            if "could not copy" in raw.lower() or "copy" in raw.lower() and "database" in raw.lower():
                # Edge/Chrome が起動中だとDBファイルのコピーに失敗する
                msg = (
                    "ブラウザのCookieデータベースのコピーに失敗しました。\n"
                    "Edge・Chrome（Chromiumベース）は起動中にファイルがロックされます。\n"
                    "【対処法】すべてのEdge / Chromeウィンドウを閉じてから再試行してください。\n"
                    "タスクマネージャーでedge.exe / chrome.exeが残っていないか確認してください。\n"
                    f"（詳細: {raw}）"
                )
            elif "locked" in raw.lower() or "database" in raw.lower():
                msg = (
                    "Cookieの読み取りに失敗しました（データベースがロックされています）。\n"
                    "対象ブラウザが起動中の場合は閉じてから再試行してください。\n"
                    "すべてのウィンドウを閉じてから実行してください。\n"
                    f"（詳細: {raw}）"
                )
            elif "not installed" in raw.lower() or "not found" in raw.lower():
                msg = (
                    "指定したブラウザが見つかりません。\n"
                    "ブラウザがインストールされているか確認してください。\n"
                    f"（詳細: {raw}）"
                )
            elif "decrypt" in raw.lower() or "unable to" in raw.lower():
                msg = (
                    "Cookieの復号化に失敗しました。\n"
                    "すべてのブラウザウィンドウを閉じてから再試行してください。\n"
                    "それでも失敗する場合は別のブラウザ（Firefox等）を試してください。\n"
                    f"（詳細: {raw}）"
                )
            else:
                msg = f"Cookie取得エラー: {raw}"

        # ── HTTP エラー ──────────────────────────────────────────────────────
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

        # ── 認証 ────────────────────────────────────────────────────────────
        elif "Sign in" in raw or "login" in raw.lower():
            msg = (
                "ログインが必要な動画です。\n"
                "「Cookieブラウザ」でログイン済みのブラウザを選択してください。"
            )

        # ── DRM ─────────────────────────────────────────────────────────────
        elif "DRM" in raw or "Widevine" in raw or "drm" in raw.lower():
            msg = (
                "DRM保護されたコンテンツはダウンロードできません。\n"
                "「ブラウザ内視聴モード」ボタンを使用してください。"
            )

        return msg

    def get_progress(self, job_id: str) -> dict:
        """ダウンロード進捗を取得"""
        return self.active_downloads.get(job_id, {"status": "unknown"})


# シングルトン
video_downloader = VideoDownloader()
