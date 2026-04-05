"""動画ダウンロード（yt-dlpラッパー）
任意の配信URL（YouTube, Twitter, Bilibili, ニコニコ等）を yt-dlp でダウンロードする。
完了後は localfile:// 形式の絶対URLを返すため、Electron のカスタムプロトコルで
そのまま再生できる。
"""
import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional


try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


class VideoDownloader:

    def __init__(self):
        # cwd は Electron が appPath を設定済みなので相対パスで OK
        self.download_dir = Path(os.path.abspath("./videos"))
        self.download_dir.mkdir(exist_ok=True)
        self.active_downloads: dict[str, dict] = {}

    def create_job_id(self) -> str:
        return str(uuid.uuid4())

    async def start_download(self, url: str, job_id: str, quality: str = "720") -> None:
        """非同期でダウンロードを開始。進捗は job_id で管理。
        quality: "360" / "480" / "720" / "1080" / "best"
        """
        if not YT_DLP_AVAILABLE:
            self.active_downloads[job_id] = {
                "status": "error",
                "error": "yt-dlp がインストールされていません (pip install yt-dlp)",
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

        yt_opts = {
            "outtmpl": str(self.download_dir / f"{job_id}.%(ext)s"),
            "format": fmt,
            "merge_output_format": "mp4",
            "progress_hooks": [lambda d: self._update_progress(job_id, d)],
            "quiet": True,
            "no_warnings": True,
        }

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._download_sync(url, yt_opts, job_id)
            )
        except Exception as e:
            self.active_downloads[job_id] = {
                "status": "error",
                "error": str(e),
            }

    def _download_sync(self, url: str, yt_opts: dict, job_id: str) -> None:
        """同期ダウンロード本体（run_in_executor で別スレッド実行）"""
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])

        # yt-dlp が "finished" フックを発火する時点はマージ前の場合がある。
        # ydl.download() が返った後にファイルを検索して確実に完了パスを取得する。
        output_files = sorted(
            f for f in self.download_dir.glob(f"{job_id}.*")
            if f.suffix not in {".part", ".ytdl", ".tmp"}
        )
        if output_files:
            abs_path = str(output_files[0].resolve())
            # Windows パスをフォワードスラッシュに変換して localfile:// URL を生成
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
        """ダウンロード進捗フック（yt-dlp から呼ばれる）"""
        if d["status"] == "downloading":
            self.active_downloads[job_id] = {
                "status": "downloading",
                "percent": d.get("_percent_str", "0%").strip(),
                "speed": d.get("_speed_str", "").strip(),
                "eta": d.get("_eta_str", "").strip(),
            }
        elif d["status"] == "finished":
            # 個別ストリームのダウンロード完了（マージがあればまだ続く）
            self.active_downloads[job_id] = {
                "status": "processing",
                "percent": "100%",
                "speed": "",
                "eta": "",
            }

    def get_progress(self, job_id: str) -> dict:
        """ダウンロード進捗を取得"""
        return self.active_downloads.get(job_id, {"status": "unknown"})


# シングルトン
video_downloader = VideoDownloader()
