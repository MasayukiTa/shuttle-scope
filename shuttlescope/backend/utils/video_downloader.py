"""YouTube動画ダウンロード（yt-dlpラッパー）"""
import asyncio
import uuid
from pathlib import Path
from typing import Optional

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


class VideoDownloader:
    DOWNLOAD_DIR = Path("./videos")

    def __init__(self):
        self.DOWNLOAD_DIR.mkdir(exist_ok=True)
        self.active_downloads: dict[str, dict] = {}

    def create_job_id(self) -> str:
        """ダウンロードジョブIDを生成"""
        return str(uuid.uuid4())

    async def start_download(self, url: str, job_id: str, quality: str = "1080") -> None:
        """非同期でダウンロードを開始。進捗をjob_idで管理。
        quality: "360" / "480" / "720" / "1080" / "best"
        """
        if not YT_DLP_AVAILABLE:
            self.active_downloads[job_id] = {
                "status": "error",
                "error": "yt-dlpがインストールされていません",
            }
            return

        self.active_downloads[job_id] = {"status": "pending"}

        # 画質に応じたformat指定
        # YouTube は映像と音声が別ストリームなので bestvideo+bestaudio でマージする
        height = quality if quality != "best" else "2160"
        fmt = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={height}]+bestaudio"
            f"/best[height<={height}]"
            "/best"
        )

        yt_opts = {
            "outtmpl": str(self.DOWNLOAD_DIR / f"{job_id}.%(ext)s"),
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
        """同期ダウンロード（run_in_executorで実行）"""
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])

    def _update_progress(self, job_id: str, d: dict) -> None:
        """ダウンロード進捗を更新"""
        if d["status"] == "downloading":
            self.active_downloads[job_id] = {
                "status": "downloading",
                "percent": d.get("_percent_str", "0%").strip(),
                "speed": d.get("_speed_str", "").strip(),
                "eta": d.get("_eta_str", "").strip(),
            }
        elif d["status"] == "finished":
            self.active_downloads[job_id] = {
                "status": "complete",
                "filepath": d["filename"],
            }

    def get_progress(self, job_id: str) -> dict:
        """ダウンロード進捗を取得"""
        return self.active_downloads.get(job_id, {"status": "unknown"})

    def get_local_path(self, job_id: str) -> Optional[str]:
        """ダウンロード完了ファイルのパスを取得"""
        info = self.active_downloads.get(job_id, {})
        if info.get("status") == "complete":
            return info.get("filepath")
        return None


# シングルトン
video_downloader = VideoDownloader()
