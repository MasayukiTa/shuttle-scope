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
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path


try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


def _resolve_deno_path() -> str | None:
    """deno 実行ファイルのフルパスを探索する。

    yt-dlp は自プロセスの PATH から deno を探すが、Electron/bat 起動時に
    PATH が古いキャッシュを使っていると WinGet Links が含まれない。
    明示的にフルパスを渡すことで回避する。
    """
    found = shutil.which("deno")
    if found:
        return found
    # Windows: winget が symlink を置くデフォルト場所
    if platform.system() == "Windows":
        home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        candidate = os.path.join(home, r"AppData\Local\Microsoft\WinGet\Links\deno.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


_DENO_PATH = _resolve_deno_path()

# yt-dlp が対応しているブラウザ名
SUPPORTED_BROWSERS = {"chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "safari"}

# Windows 上でCookie DBがロックされやすい Chromium ベースブラウザ
_CHROMIUM_BROWSERS = {"chrome", "edge", "brave", "vivaldi", "opera", "chromium"}

_CHROMIUM_PROFILE_DIRS = {
    "chrome":   r"Google\Chrome\User Data",
    "edge":     r"Microsoft\Edge\User Data",
    "brave":    r"BraveSoftware\Brave-Browser\User Data",
    "vivaldi":  r"Vivaldi\User Data",
    "opera":    r"Opera Software\Opera Stable",
    "chromium": r"Chromium\User Data",
}


def _make_unlocked_profile_copy(browser: str) -> str | None:
    """Windows でロックされた Chromium 系 Cookie DB を sqlite3 immutable モードでコピーする。

    Edge/Chrome は起動中（または WebView2 が常駐中）でも immutable=1 で読み取り可能。
    コピーしたプロファイルディレクトリのパスを返す（yt-dlp の profile 引数に渡す）。
    失敗時は None（呼び出し元は通常の cookiesfrombrowser にフォールバックする）。
    """
    if platform.system() != "Windows":
        return None

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    rel = _CHROMIUM_PROFILE_DIRS.get(browser)
    if not local_app_data or not rel:
        return None

    profile_dir = Path(local_app_data) / rel
    if not profile_dir.exists():
        return None

    # Cookie DBパス候補（Chrome 96+ は Network/Cookies、旧バージョンは Cookies）
    cookie_db_candidates = [
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
    ]
    cookie_db = next((p for p in cookie_db_candidates if p.exists()), None)

    local_state = profile_dir / "Local State"
    if not cookie_db or not local_state.exists():
        return None

    tmp_dir: Path | None = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="shuttlescope_cookies_"))

        # yt-dlp が期待するディレクトリ構造を再現:
        # <profile>/Default/Network/Cookies  （新形式）
        # <profile>/Default/Cookies          （旧形式、両方用意して確実に読めるようにする）
        for rel_path in ("Default/Network/Cookies", "Default/Cookies"):
            dst_path = tmp_dir / rel_path
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            # immutable=1: ロック中のDBをコピーせず直接読み込む
            # URI の区切り文字はスラッシュ必須（Windows パスもフォワードスラッシュに変換）
            uri = "file:///" + cookie_db.as_posix().lstrip("/") + "?immutable=1"
            src_conn = sqlite3.connect(uri, uri=True)
            dst_conn = sqlite3.connect(str(dst_path))
            src_conn.backup(dst_conn)
            src_conn.close()
            dst_conn.close()

        # 暗号化キー（Local State）は通常ロックされていない
        shutil.copy2(str(local_state), str(tmp_dir / "Local State"))

        return str(tmp_dir)
    except Exception as e:
        print(f"[shuttlescope] cookie unlock failed ({browser}): {e}", file=sys.stderr)
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return None


class _YtDlpLogger:
    """yt-dlp のログを制御するカスタムロガー。

    no_warnings=True だけでは抑制できない "Could not copy cookie database"
    系のメッセージを確実にフィルタリングする。
    """

    _SUPPRESS_PATTERNS = (
        "could not copy",
        "cookie database",
        "cookies from browser",
        "cookiesfrombrowser",
    )

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        lower = msg.lower()
        if any(p in lower for p in self._SUPPRESS_PATTERNS):
            return
        print(f"[yt-dlp] {msg}", file=sys.stderr)

    def error(self, msg: str) -> None:
        lower = msg.lower()
        if any(p in lower for p in self._SUPPRESS_PATTERNS):
            return
        print(f"[yt-dlp ERROR] {msg}", file=sys.stderr)


def _check_ffmpeg() -> bool:
    """ffmpegがPATH上に存在するか確認する"""
    return shutil.which("ffmpeg") is not None


class VideoDownloader:

    # 進捗フックの最小更新間隔（秒）。yt-dlp はチャンクごとに呼ぶため、
    # これ未満の呼び出しは dict 書き換えをスキップしてCPU負荷を下げる。
    _PROGRESS_THROTTLE_SEC = 0.5

    def __init__(self):
        # cwd は Electron が appPath を設定済みなので相対パスで解決できる
        self.download_dir = Path(os.path.abspath("./videos"))
        self.download_dir.mkdir(exist_ok=True)
        self.active_downloads: dict[str, dict] = {}
        # ffmpeg 可用性をインスタンス生成時に一度だけ確認する
        self.ffmpeg_available: bool = _check_ffmpeg()
        # job_id → 最後に進捗を書き込んだ時刻
        self._progress_last_update: dict[str, float] = {}
        # 起動時に孤児化した中途ファイルを削除する。
        # job_id は UUID なので再起動後は同じパスが再利用されることはなく、
        # yt-dlp の resume (.part からの継続DL) も効かないため残しても意味がない。
        self._cleanup_orphan_partials()

    def _cleanup_orphan_partials(self) -> None:
        """download_dir 内の .part / .ytdl / .tmp を削除する。"""
        removed = 0
        for f in self.download_dir.glob("*"):
            if f.is_file() and f.suffix in {".part", ".ytdl", ".tmp"}:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        if removed:
            print(f"[shuttlescope] cleaned up {removed} orphan partial download file(s)", file=sys.stderr)

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
        cookies_file: str = "",
    ) -> None:
        """非同期でダウンロードを開始。進捗は job_id で管理。

        Args:
            url:            ダウンロード対象URL
            job_id:         進捗管理用UUID
            quality:        "360" / "480" / "720" / "1080" / "best"
            cookie_browser: （Electron 互換用 / Web では使用禁止）使用するブラウザ名
            cookies_file:   yt-dlp 形式 cookies.txt の絶対パス（優先）
                            ジョブ完了後に呼び出し元で削除する責務。
        """
        if not YT_DLP_AVAILABLE:
            self._set_status(job_id, {
                "status": "error",
                "error": "yt-dlp がインストールされていません（pip install yt-dlp）",
            })
            return

        self._set_status(job_id, {
            "status": "pending",
            "ffmpeg_available": self.ffmpeg_available,
        })

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
            # カスタムロガー: cookie DB コピー失敗の stderr 出力を抑制
            "logger": _YtDlpLogger(),
        }

        # JS ランタイム（YouTube 抽出に必要）。deno が PATH 解決できない環境向けに
        # 明示的にフルパスを渡す（winget install 直後のキャッシュ問題回避）。
        if _DENO_PATH:
            yt_opts["js_runtimes"] = {"deno": {"path": _DENO_PATH}}

        # ffmpeg がある場合のみ merge_output_format を指定
        # （指定すると ffmpeg がない環境で強制マージが走りエラーになる）
        if self.ffmpeg_available:
            yt_opts["merge_output_format"] = "mp4"

        # ── Cookie 設定 ──────────────────────────────────────────────────────
        # 1. cookies_file (ユーザが UI からアップロードした cookies.txt) 最優先
        #    - 一時ファイル、ジョブ終了で呼び出し元が削除
        #    - ネットワーク経由は HTTPS (TLS 1.3) + Cloudflare Tunnel で傍受対策
        # 2. cookie_browser (Electron 経由・本番環境の chrome cookie 直接読出し)
        #    - 現在は廃止予定。cookies_file が優先される
        unlocked_profile: str | None = None
        if cookies_file and os.path.isfile(cookies_file):
            yt_opts["cookiefile"] = cookies_file
        else:
            browser = cookie_browser.strip().lower()
            if browser and browser in SUPPORTED_BROWSERS:
                if browser in _CHROMIUM_BROWSERS:
                    unlocked_profile = _make_unlocked_profile_copy(browser)
                if unlocked_profile:
                    yt_opts["cookiesfrombrowser"] = (browser, unlocked_profile, None, None)
                else:
                    yt_opts["cookiesfrombrowser"] = (browser,)

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._download_sync(url, yt_opts, job_id)
            )
        except Exception as e:
            self._set_status(job_id, {
                "status": "error",
                "error": self._format_error(str(e)),
            })
        finally:
            if unlocked_profile:
                shutil.rmtree(unlocked_profile, ignore_errors=True)

    # ── 内部メソッド ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_ssl_error(raw: str) -> bool:
        return (
            "CERTIFICATE_VERIFY_FAILED" in raw
            or "certificate verify failed" in raw.lower()
            or "ssl: certificate" in raw.lower()
        )

    def _download_sync(self, url: str, yt_opts: dict, job_id: str) -> None:
        """同期ダウンロード本体（run_in_executor で別スレッド実行）"""
        try:
            with yt_dlp.YoutubeDL(yt_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            # 企業プロキシ等のSSL証明書エラー → 検証スキップで再試行
            if self._is_ssl_error(str(e)):
                retry_opts = {**yt_opts, "nocheckcertificate": True}
                with yt_dlp.YoutubeDL(retry_opts) as ydl:
                    ydl.download([url])
            else:
                raise

        # yt-dlp が "finished" フックを発火する時点はマージ前の場合がある。
        # ydl.download() 完了後にファイルを glob 検索して確実に完了パスを取得。
        output_files = sorted(
            f for f in self.download_dir.glob(f"{job_id}.*")
            if f.suffix not in {".part", ".ytdl", ".tmp"}
        )
        if output_files:
            # ブラウザ <video> から /api/v1/uploads/video/by_match/{id}/stream で
            # 配信するため、server://{filename} 形式で記録する。
            # download_dir == UPLOAD_DIR (./videos) なのでそのまま stream endpoint が解決する。
            # 過去は localfile:/// 絶対パスを返していたが Electron 専用で
            # ブラウザでは再生不能だった。
            fname = output_files[0].name
            server_url = f"server://{fname}"
            self._set_status(job_id, {
                "status": "complete",
                "filepath": server_url,
            })
        else:
            self._set_status(job_id, {
                "status": "error",
                "error": "ダウンロード後に出力ファイルが見つかりません",
            })

    def _update_progress(self, job_id: str, d: dict) -> None:
        """yt-dlp 進捗フック（500ms スロットリング付き）"""
        if not hasattr(self, "_progress_last_update"):
            self._progress_last_update = {}
        if d["status"] == "downloading":
            now = time.monotonic()
            last = self._progress_last_update.get(job_id, 0.0)
            if now - last < self._PROGRESS_THROTTLE_SEC:
                return
            self._progress_last_update[job_id] = now
            self._set_status(job_id, {
                "status": "downloading",
                "percent": d.get("_percent_str", "0%").strip(),
                "speed": d.get("_speed_str", "").strip(),
                "eta": d.get("_eta_str", "").strip(),
            })
        elif d["status"] == "finished":
            # 個別ストリームのダウンロード完了（マージ処理がある場合はまだ続く）
            self._set_status(job_id, {
                "status": "processing",
                "percent": "100%",
                "speed": "",
                "eta": "",
            })

    @staticmethod
    def _format_error(raw: str) -> str:
        """yt-dlp のエラーメッセージを日本語で補足する"""
        msg = raw

        # ── SSL証明書エラー（最優先: 他のキーワードに埋もれないよう先に判定） ──────
        if (
            "CERTIFICATE_VERIFY_FAILED" in raw
            or "certificate verify failed" in raw.lower()
            or "ssl: certificate" in raw.lower()
        ):
            msg = (
                "SSL証明書の検証に失敗しました。\n"
                "企業ネットワーク（プロキシ・VPN・SSL検査）が原因の場合があります。\n"
                "自動的に証明書検証をスキップして再試行しましたが失敗しました。\n"
                "【対処法】ネットワーク管理者にSSL検査の除外設定を依頼するか、\n"
                "システムの証明書ストアに企業CAを追加してください。\n"
                f"（詳細: {raw}）"
            )

        # ── ffmpeg 関連 ──────────────────────────────────────────────────────
        elif "ffmpeg" in raw.lower() and (
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
            if "could not copy" in raw.lower() or ("copy" in raw.lower() and "database" in raw.lower()):
                # Edge/Chrome・WebView2 が常駐中だとDBファイルのコピーに失敗する
                msg = (
                    "ブラウザのCookieデータベースのコピーに失敗しました。\n"
                    "【主な原因】msedgewebview2.exe（Edge WebView2）が常駐していると\n"
                    "ブラウザを閉じた後もDBがロックされ続けます。\n"
                    "【対処法①】タスクマネージャーで以下をすべて終了してから再試行:\n"
                    "  msedge.exe / chrome.exe / msedgewebview2.exe\n"
                    "【対処法②】yt-dlp を最新版に更新してから再試行:\n"
                    "  pip install -U yt-dlp\n"
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

    def _set_status(self, job_id: str, payload: dict) -> None:
        """active_downloads[job_id] を上書きしつつ match_id を保持する。
        各 progress hook / finalize / error path から呼ぶことで、UI 用の
        match_id 関連付けが消えないようにする。
        """
        prev_mid = (self.active_downloads.get(job_id) or {}).get("match_id")
        if prev_mid is not None:
            payload = {**payload, "match_id": prev_mid}
        self.active_downloads[job_id] = payload

    def get_progress(self, job_id: str) -> dict:
        """ダウンロード進捗を取得"""
        return self.active_downloads.get(job_id, {"status": "unknown"})

    def attach_match_id(self, job_id: str, match_id: int) -> None:
        """ジョブと match を関連付ける (UI が match 単位で進捗を表示するため)。
        まだ start_download が呼ばれていないタイミングで呼ぶことを許容するため、
        entry が無ければ "queued" status で先に作る。後で start_download が
        "pending"/"downloading" に上書きする。
        """
        info = self.active_downloads.get(job_id)
        if info is None:
            self.active_downloads[job_id] = {"status": "queued", "match_id": int(match_id)}
        else:
            info["match_id"] = int(match_id)

    def active_jobs_by_match(self) -> dict[int, dict]:
        """進行中 (downloading/pending) のジョブを match_id でグループ化して返す。
        UI が試合一覧で「DL 中」バッジを出すための index。
        """
        out: dict[int, dict] = {}
        for jid, info in self.active_downloads.items():
            mid = info.get("match_id")
            if not isinstance(mid, int):
                continue
            st = info.get("status", "")
            if st in ("queued", "pending", "downloading", "processing", "starting"):
                out[mid] = {
                    "job_id": jid,
                    "status": st,
                    "percent": info.get("percent"),
                    "speed": info.get("speed"),
                    "eta": info.get("eta"),
                }
        return out


# シングルトン
video_downloader = VideoDownloader()
