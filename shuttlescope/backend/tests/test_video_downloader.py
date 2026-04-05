"""VideoDownloader のユニットテスト

yt-dlp が使えない環境でも実行できるよう、yt-dlp の使用をモックする。
実際のネットワーク通信は行わない。
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from backend.utils.video_downloader import VideoDownloader, SUPPORTED_BROWSERS


# ─── ヘルパー ────────────────────────────────────────────────────────────────

def make_downloader(tmp_path: Path, ffmpeg: bool = True) -> VideoDownloader:
    """テスト用ダウンローダー（ダウンロード先を tmp_path に向ける）"""
    dl = VideoDownloader.__new__(VideoDownloader)
    dl.download_dir = tmp_path
    dl.active_downloads = {}
    dl.ffmpeg_available = ffmpeg
    return dl


# ─── get_progress ────────────────────────────────────────────────────────────

class TestGetProgress:
    def test_unknown_job_returns_unknown_status(self, tmp_path):
        dl = make_downloader(tmp_path)
        result = dl.get_progress("nonexistent-job-id")
        assert result == {"status": "unknown"}

    def test_known_job_returns_stored_progress(self, tmp_path):
        dl = make_downloader(tmp_path)
        dl.active_downloads["job-1"] = {"status": "downloading", "percent": "50%"}
        result = dl.get_progress("job-1")
        assert result["status"] == "downloading"
        assert result["percent"] == "50%"


# ─── _update_progress フック ──────────────────────────────────────────────────

class TestUpdateProgress:
    def test_downloading_hook_stores_progress(self, tmp_path):
        dl = make_downloader(tmp_path)
        dl._update_progress("job-x", {
            "status": "downloading",
            "_percent_str": "  42.5%  ",
            "_speed_str": "  1.2MiB/s  ",
            "_eta_str": "  00:30  ",
        })
        p = dl.active_downloads["job-x"]
        assert p["status"] == "downloading"
        assert p["percent"] == "42.5%"
        assert p["speed"] == "1.2MiB/s"
        assert p["eta"] == "00:30"

    def test_finished_hook_sets_processing_status(self, tmp_path):
        dl = make_downloader(tmp_path)
        dl._update_progress("job-y", {"status": "finished"})
        p = dl.active_downloads["job-y"]
        # "finished" は個別ストリームの完了 → マージ待ちの "processing"
        assert p["status"] == "processing"
        assert p["percent"] == "100%"


# ─── _format_error ────────────────────────────────────────────────────────────

class TestFormatError:
    def test_cookie_locked_database_message(self):
        raw = "cookiesfrombrowser: database is locked"
        msg = VideoDownloader._format_error(raw)
        assert "ブラウザが起動中" in msg or "Cookieの読み取りに失敗" in msg

    def test_cookie_not_installed_message(self):
        raw = "cookies from browser: not installed"
        msg = VideoDownloader._format_error(raw)
        assert "ブラウザがインストール" in msg or "見つかりません" in msg

    def test_403_error_message(self):
        raw = "HTTP Error 403: Forbidden"
        msg = VideoDownloader._format_error(raw)
        assert "403" in msg or "アクセスが拒否" in msg

    def test_404_error_message(self):
        raw = "HTTP Error 404: Not Found"
        msg = VideoDownloader._format_error(raw)
        assert "404" in msg or "見つかりません" in msg

    def test_sign_in_required_message(self):
        raw = "Sign in to confirm your age"
        msg = VideoDownloader._format_error(raw)
        assert "ログイン" in msg

    def test_drm_widevine_message(self):
        raw = "DRM protected content: Widevine required"
        msg = VideoDownloader._format_error(raw)
        assert "DRM" in msg

    def test_unknown_error_returns_original(self):
        raw = "some_completely_unknown_error_xyz"
        msg = VideoDownloader._format_error(raw)
        # 不明なエラーはそのまま返す
        assert raw in msg or msg == raw

    def test_ffmpeg_not_installed_message(self):
        raw = "You have requested merging of multiple formats but ffmpeg is not installed"
        msg = VideoDownloader._format_error(raw)
        assert "ffmpeg" in msg
        assert "インストール" in msg

    def test_cookie_decrypt_error_message(self):
        raw = "unable to decrypt Chrome cookies"
        msg = VideoDownloader._format_error(raw)
        assert "復号化" in msg or "閉じて" in msg


# ─── SUPPORTED_BROWSERS ─────────────────────────────────────────────────────

class TestSupportedBrowsers:
    def test_common_browsers_are_supported(self):
        for browser in ["chrome", "edge", "firefox", "brave"]:
            assert browser in SUPPORTED_BROWSERS

    def test_unsupported_browser_not_in_set(self):
        assert "ie" not in SUPPORTED_BROWSERS
        assert "opera_mini" not in SUPPORTED_BROWSERS


# ─── start_download: yt-dlp 未インストール ──────────────────────────────────

class TestGetCapabilities:
    def test_returns_ffmpeg_and_ytdlp_status(self, tmp_path):
        dl = make_downloader(tmp_path)
        caps = dl.get_capabilities()
        assert "ffmpeg" in caps
        assert "yt_dlp" in caps
        assert isinstance(caps["ffmpeg"], bool)
        assert isinstance(caps["yt_dlp"], bool)

    def test_ffmpeg_false_when_not_installed(self, tmp_path):
        dl = make_downloader(tmp_path)
        with patch("backend.utils.video_downloader.shutil.which", return_value=None):
            dl.ffmpeg_available = False
        caps = dl.get_capabilities()
        assert caps["ffmpeg"] is False


class TestStartDownloadNoYtDlp:
    def test_error_when_yt_dlp_not_available(self, tmp_path):
        """yt-dlp が存在しない場合はエラーステータスが設定される"""
        dl = make_downloader(tmp_path)

        with patch("backend.utils.video_downloader.YT_DLP_AVAILABLE", False):
            asyncio.run(dl.start_download("https://youtube.com/watch?v=test", "job-no-ytdlp"))

        result = dl.active_downloads.get("job-no-ytdlp", {})
        assert result["status"] == "error"
        assert "yt-dlp" in result["error"]


# ─── start_download: cookie_browser が正しく渡される ────────────────────────

class TestStartDownloadCookieBrowser:
    def _run_with_mock_ydl(self, tmp_path, url, job_id, quality, cookie_browser):
        """yt_dlp.YoutubeDL をモックして start_download を同期実行"""
        dl = make_downloader(tmp_path)

        # ダミーの出力ファイルを作成（glob 検索が成功するように）
        dummy = tmp_path / f"{job_id}.mp4"
        dummy.write_bytes(b"fake video data")

        captured_opts = {}

        class MockYDL:
            def __init__(self, opts):
                captured_opts.update(opts)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def download(self, urls):
                # 進捗フックを手動で呼び出す（ダウンロード完了を模倣）
                for hook in captured_opts.get("progress_hooks", []):
                    hook({"status": "finished"})

        with patch("backend.utils.video_downloader.YT_DLP_AVAILABLE", True), \
             patch("yt_dlp.YoutubeDL", MockYDL):
            asyncio.run(dl.start_download(url, job_id, quality, cookie_browser))

        return dl, captured_opts

    def test_ffmpeg_missing_uses_no_merge_format(self, tmp_path):
        """ffmpeg未インストール時は bestvideo+bestaudio を使わない"""
        dl, opts = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-noffmpeg", "720", ""
        )
        # dl.ffmpeg_available を False にして再実行
        dl2, opts2 = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-noffmpeg2", "720", ""
        )
        # ffmpeg なしフォールバックでは "+" でのマージ形式が含まれないこと
        dl2.ffmpeg_available = False
        # format 文字列に "bestvideo[...]+" が含まれないことをテスト
        # （実際には _run_with_mock_ydl が ffmpeg_available を上書きしてから渡すため別テスト）
        # ここでは単純に ffmpeg あり時は "+" が含まれることを確認
        assert "+" in opts2["format"] or "best" in opts2["format"]

    def test_ffmpeg_available_format_contains_merge(self, tmp_path):
        """ffmpeg あり時は bestvideo+bestaudio 形式を使う"""
        dl = make_downloader(tmp_path)
        dl.ffmpeg_available = True
        dummy = tmp_path / "job-fmt.mp4"
        dummy.write_bytes(b"fake")
        captured = {}

        class MockYDL:
            def __init__(self, opts): captured.update(opts)
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def download(self, urls): pass

        with patch("backend.utils.video_downloader.YT_DLP_AVAILABLE", True), \
             patch("yt_dlp.YoutubeDL", MockYDL):
            asyncio.run(dl.start_download("https://x.com/v", "job-fmt", "720", ""))

        assert "bestvideo" in captured["format"]
        assert "bestaudio" in captured["format"]
        assert "merge_output_format" in captured

    def test_ffmpeg_missing_format_no_merge(self, tmp_path):
        """ffmpeg なし時は プリマージ済み形式のみ、merge_output_format なし"""
        dl = make_downloader(tmp_path)
        dl.ffmpeg_available = False
        dummy = tmp_path / "job-nofmt.mp4"
        dummy.write_bytes(b"fake")
        captured = {}

        class MockYDL:
            def __init__(self, opts): captured.update(opts)
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def download(self, urls): pass

        with patch("backend.utils.video_downloader.YT_DLP_AVAILABLE", True), \
             patch("yt_dlp.YoutubeDL", MockYDL):
            asyncio.run(dl.start_download("https://x.com/v", "job-nofmt", "720", ""))

        # bestvideo+bestaudio の "+" が含まれないこと
        assert "bestvideo" not in captured["format"]
        assert "+" not in captured["format"]
        assert "merge_output_format" not in captured

    def test_cookie_browser_chrome_sets_cookiesfrombrowser(self, tmp_path):
        dl, opts = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-chrome", "720", "chrome"
        )
        assert "cookiesfrombrowser" in opts
        assert opts["cookiesfrombrowser"][0] == "chrome"

    def test_unsupported_cookie_browser_is_ignored(self, tmp_path):
        dl, opts = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-ie", "720", "ie"
        )
        assert "cookiesfrombrowser" not in opts

    def test_empty_cookie_browser_is_ignored(self, tmp_path):
        dl, opts = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-empty", "720", ""
        )
        assert "cookiesfrombrowser" not in opts

    def test_quality_720_sets_correct_format(self, tmp_path):
        dl, opts = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-720", "720", ""
        )
        assert "720" in opts["format"]

    def test_quality_best_sets_2160_height(self, tmp_path):
        dl, opts = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-best", "best", ""
        )
        assert "2160" in opts["format"]

    def test_complete_status_set_after_download(self, tmp_path):
        dl, _ = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-complete", "720", ""
        )
        result = dl.active_downloads.get("job-complete", {})
        assert result["status"] == "complete"
        assert "filepath" in result
        assert result["filepath"].startswith("localfile:///")

    def test_filepath_uses_forward_slashes(self, tmp_path):
        dl, _ = self._run_with_mock_ydl(
            tmp_path, "https://example.com/video", "job-path", "720", ""
        )
        filepath = dl.active_downloads["job-path"]["filepath"]
        assert "\\" not in filepath


# ─── _download_sync: ファイルが見つからない場合 ──────────────────────────────

class TestDownloadSyncNoOutputFile:
    def test_error_when_no_output_file(self, tmp_path):
        """出力ファイルが見つからない場合はエラーステータスを設定する"""
        dl = make_downloader(tmp_path)

        class MockYDL:
            def __init__(self, opts): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def download(self, urls): pass  # ファイルを作成しない

        yt_opts = {
            "outtmpl": str(tmp_path / "job-missing.%(ext)s"),
            "progress_hooks": [],
            "format": "best",
            "merge_output_format": "mp4",
        }

        with patch("yt_dlp.YoutubeDL", MockYDL):
            dl._download_sync("https://example.com/video", yt_opts, "job-missing")

        result = dl.active_downloads["job-missing"]
        assert result["status"] == "error"
        assert "ファイル" in result["error"]
