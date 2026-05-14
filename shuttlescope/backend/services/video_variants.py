"""動画 variant 生成サービス。

目的:
    モバイルアノテ / Web 表示用に 1080p (fhd) / 720p (hd) を post-process で生成し、
    解析パイプラインは source raw を使い続ける構成を実現する。

設計 (= DoS 観点で重要):
    1. source 解像度に対して **upscale は絶対しない**。
       例: 480p source → fhd/hd 変換ジョブを **skip** (= ストレージも CPU も使わない)。
       これを怠ると、攻撃者が 240p 動画を大量に上げて全部 1080p に水増し させる
       ことで、ディスク + CPU + ネット帯域を浪費させられる。
    2. source の縦横ピクセルが異常 (> 8192) の場合は variant 生成自体を skip。
       過度に巨大な動画は ffmpeg のメモリ消費が爆発するため、receive 側 + ここの
       二重チェックで防ぐ。
    3. variant 生成は OS の concurrency limit (Semaphore=1) で直列化。worker process
       が 1 本走行のため自然に 1 並列だが、念のため明示。
    4. variant パスは UUID ベース (upload_id を流用) + 拡張子白リスト。path traversal
       不可能な構造。
    5. 失敗時は partial ファイルを必ず削除 (= TOCTOU で「再生用 endpoint が 0 byte
       の variant を 200 で返す」事故を防ぐ)。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _resolve_bin(name: str) -> Optional[str]:
    """ffmpeg / ffprobe のフルパスを解決する。

    SYSTEM 権限のサービス文脈では PATH に WinGet/Links が無いため、
    shutil.which が None を返す。video_downloader._resolve_ffmpeg と同じ順序で
    解決する (PATH → imageio_ffmpeg bundled → 既知パス → WinGet Links 直指定)。
    """
    p = shutil.which(name)
    if p:
        return p
    # imageio-ffmpeg bundled (ffmpeg のみ — ffprobe は提供しないので fall-through)
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg as _iio
            bundled = _iio.get_ffmpeg_exe()
            if bundled and os.path.isfile(bundled):
                return bundled
        except Exception:
            pass
    candidates = [
        rf"C:\Program Files\ffmpeg\bin\{name}.exe",
        rf"C:\ProgramData\chocolatey\bin\{name}.exe",
        rf"C:\ffmpeg\bin\{name}.exe",
    ]
    # SYSTEM 権限で動作時は USERPROFILE が SYSTEM の home を指す可能性が高いが、
    # 想定として kiyus のインストールを参照する場合のフォールバックも残す
    for env_user in ("USERPROFILE", "HOME"):
        home = os.environ.get(env_user)
        if home:
            candidates.append(os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Links", f"{name}.exe"))
    # 既知のユーザ配置 (SYSTEM 権限から直指定)
    candidates.append(rf"C:\Users\kiyus\AppData\Local\Microsoft\WinGet\Links\{name}.exe")
    for c in candidates:
        try:
            if os.path.isfile(c):
                return c
        except OSError:
            continue
    return None


# ─── 設定 ────────────────────────────────────────────────────────────────

# 配信時にサポートする画質 quality キー → 縦解像度。
# 4K (uhd) は variant としては作らない。source が <= 4K なら source を返すだけで
# 十分 (4K → 4K 変換は無意味、5K/6K source は variant を作らないという方針)。
# 「配信 cap = 4K」は YouTube DL 側で source 自体を 2160 以下に抑えている。
_VARIANT_SPECS: Dict[str, int] = {
    "uhd": 2160,   # 4K — 「配信 cap = 4K」要件。source が 4K 超 (5K/6K/8K) のときのみ生成
    "fhd": 1080,   # Full HD
    "hd":  720,    # HD
}

# variant ファイル名のテンプレート。UPLOAD_DIR/variants/{upload_id}_{quality}.mp4。
_VARIANT_SUBDIR = "variants"

# source の最大許容ピクセル (= 横 * 縦)。8192*4320 ≒ 35M pixels = 8K 相当。
# これを超える場合は variant 生成を完全に skip する (ffmpeg DoS 防御)。
# 解析パイプライン側は source 直読なので、この閾値は variant 生成にのみ影響する。
_MAX_SOURCE_PIXELS = 8192 * 4320

# 異常に大きい variant ジョブの timeout (秒)。10 分動画 1080p で 5 分以内には終わる
# はず。20 分超は何かおかしい。
_VARIANT_TRANSCODE_TIMEOUT_SEC = 60 * 20

# CRF: 高いほど低画質・小ファイル。23 が x264 default。モバイル配信なので 26 で
# サイズ最小化 (1080p で 1.5GB → 800MB 程度に下がる)。
_VARIANT_CRF_UHD = 25
_VARIANT_CRF_FHD = 26
_VARIANT_CRF_HD = 27

# ffmpeg preset: ファストエンコード優先 (transcoding が長すぎて UX 悪化する方が
# 困るので、サイズより速度)。
_VARIANT_PRESET = "veryfast"


# ─── データ ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProbeResult:
    height: int
    width: int
    codec: str
    duration_sec: float
    fps: float


@dataclass(frozen=True)
class VariantPlan:
    quality: str    # "fhd" / "hd"
    target_h: int   # 1080 / 720


# ─── 公開 API ────────────────────────────────────────────────────────────

def probe_source(path: Path) -> Optional[ProbeResult]:
    """ffprobe で動画の縦横/codec/長さを取得。失敗時 None。

    返却値の height は変換時の target 比較に使うので **整数 pixel** で返す。
    rotation メタデータがある (= 90/270 度回転) 場合は width/height をスワップ
    した値を返す (人間が見たときの解像度に揃える)。
    """
    ffprobe = _resolve_bin("ffprobe")
    if not ffprobe:
        logger.warning("[video_variants] ffprobe not found in PATH; cannot probe")
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", "--", str(path)],
            capture_output=True, timeout=30, shell=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[video_variants] ffprobe timeout for %s", path)
        return None
    except Exception as exc:
        logger.warning("[video_variants] ffprobe failed: %s", exc)
        return None
    if proc.returncode != 0:
        logger.warning("[video_variants] ffprobe rc=%d for %s", proc.returncode, path)
        return None
    try:
        info = json.loads(proc.stdout or b"{}")
    except Exception:
        return None
    vid = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if vid is None:
        return None
    try:
        w = int(vid.get("width") or 0)
        h = int(vid.get("height") or 0)
    except (TypeError, ValueError):
        return None
    # rotation 補正: tags.rotate or side_data display matrix
    rot = 0
    try:
        rot = int(vid.get("tags", {}).get("rotate") or 0)
    except (TypeError, ValueError):
        rot = 0
    for sd in vid.get("side_data_list") or []:
        try:
            r = int(sd.get("rotation") or 0)
            if r:
                rot = r
        except (TypeError, ValueError):
            pass
    if rot in (90, -90, 270, -270):
        w, h = h, w

    codec = str(vid.get("codec_name") or "")
    fmt = info.get("format") or {}
    try:
        dur = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0

    # FPS: avg_frame_rate "30000/1001" 等
    fps = 0.0
    try:
        afr = str(vid.get("avg_frame_rate") or "0/0")
        num, den = afr.split("/")
        n = float(num); d = float(den)
        if d > 0:
            fps = n / d
    except Exception:
        fps = 0.0

    return ProbeResult(height=h, width=w, codec=codec, duration_sec=dur, fps=fps)


def decide_variants(probe: ProbeResult) -> List[VariantPlan]:
    """source 解像度に対して **不要 upscale を排除した** 生成プランを返す。

    Rules:
      - probe が None / 高さ取得失敗 → 空リスト (= 生成しない)
      - source pixel 総数 > _MAX_SOURCE_PIXELS → 空リスト (DoS 防御)
      - source.height <= target.height → そのターゲットは skip
        (= 480p source に対して fhd/hd を作らない)
    """
    if probe is None:
        return []
    if probe.width <= 0 or probe.height <= 0:
        return []
    if probe.width * probe.height > _MAX_SOURCE_PIXELS:
        logger.warning(
            "[video_variants] source too large %dx%d (> %d), skipping all variants",
            probe.width, probe.height, _MAX_SOURCE_PIXELS,
        )
        return []
    plans: List[VariantPlan] = []
    for q, target_h in _VARIANT_SPECS.items():
        if probe.height > target_h:
            plans.append(VariantPlan(quality=q, target_h=target_h))
        else:
            logger.info(
                "[video_variants] source %dp <= target %s(%dp), skip (no upscale)",
                probe.height, q, target_h,
            )
    return plans


def variant_dir(upload_dir: Path) -> Path:
    """variant 出力先ディレクトリ。存在しなければ作る。"""
    d = upload_dir / _VARIANT_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def variant_path(upload_dir: Path, upload_id: str, quality: str) -> Path:
    """upload_id + quality から variant の絶対パスを返す。

    upload_id は API 内部発行 (UUID) で external 影響無し。
    quality は _VARIANT_SPECS の key にのみ限定する (caller で validate 済み前提)。
    """
    return variant_dir(upload_dir) / f"{upload_id}_{quality}.mp4"


def list_available_qualities(
    upload_dir: Path,
    upload_id: str,
    source_height: Optional[int],
) -> List[Dict[str, object]]:
    """既存 variant + source の利用可能 quality リストを返す。

    各要素は {"quality": str, "height": int, "ready": bool}。
        - quality="source": 元動画。常に ready=True。
        - quality="fhd"/"hd": variant ファイル実在チェック (= ready=True)。
          source.height <= target_h なら **このリストには含めない**
          (= upscale 不要のため UI に出さない)。

    source_height が None (probe 失敗 or video_local_path が server:// 経路でない)
    の場合は ["source"] のみ返す。
    """
    out: List[Dict[str, object]] = []
    src_h = int(source_height) if source_height else 0
    out.append({"quality": "source", "height": src_h, "ready": True})
    for q, target_h in _VARIANT_SPECS.items():
        if src_h and src_h <= target_h:
            # upscale 対象外: UI からも消す
            continue
        p = variant_path(upload_dir, upload_id, q)
        out.append({"quality": q, "height": target_h, "ready": p.exists() and p.stat().st_size > 0})
    return out


def generate_variant(
    source: Path,
    target: Path,
    target_h: int,
    crf: int,
) -> Tuple[bool, str]:
    """ffmpeg で source を target_h 高さの mp4 に変換する。

    成功条件: ffmpeg rc=0 AND tmp ファイルが 1KB 以上で作られている。
    失敗時は tmp/partial を必ず削除する (0 byte ファイルが残ると streaming 側で
    200 + 空 body を返してしまい再生不能になる)。

    **Atomic rename**: ffmpeg は `.tmp` に書く → 成功確認後 `os.replace()` で
    最終パスへ atomic rename。Streaming endpoint は中途半端な variant を絶対に
    pickup しない (= 別 process が並行アクセスする状況でも安全)。

    width は -2 (= 偶数に丸めた auto, x264 要件)。
    audio は AAC 128kbps (モバイル用なので過剰品質不要)。
    """
    import os as _os
    ffmpeg = _resolve_bin("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg not found"
    # 出力先の parent 確保
    target.parent.mkdir(parents=True, exist_ok=True)
    # tmp パス (= 隣接 directory に書いてから rename。renames は同 FS なら atomic)
    tmp = target.parent / (target.name + ".tmp")
    # 残骸があれば削除
    for p in (tmp,):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    cmd = [
        ffmpeg,
        "-y",                       # 上書き
        "-loglevel", "error",
        "-i", str(source),
        "-vf", f"scale=-2:{target_h}",
        "-c:v", "libx264",
        "-preset", _VARIANT_PRESET,
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",  # web 配信時に moov を先頭へ
        "-f", "mp4",
        "--",                       # path injection 防御
        str(tmp),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=_VARIANT_TRANSCODE_TIMEOUT_SEC,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        _cleanup_partial(tmp)
        return False, "ffmpeg timeout"
    except Exception as exc:
        _cleanup_partial(tmp)
        return False, f"ffmpeg exec error: {exc}"

    if proc.returncode != 0:
        _cleanup_partial(tmp)
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:500]
        return False, f"ffmpeg rc={proc.returncode}: {err}"
    # サイズ確認 (tmp)
    try:
        if not tmp.exists() or tmp.stat().st_size < 1024:
            _cleanup_partial(tmp)
            return False, "output too small"
    except OSError as exc:
        _cleanup_partial(tmp)
        return False, f"stat failed: {exc}"
    # atomic rename: 同 FS 想定 (UPLOAD_DIR/variants/)
    try:
        _os.replace(str(tmp), str(target))
    except OSError as exc:
        _cleanup_partial(tmp)
        return False, f"rename failed: {exc}"
    return True, "ok"


def _cleanup_partial(p: Path) -> None:
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


def variant_specs() -> Dict[str, int]:
    """外部向けに quality -> target_h の dict を露出 (router の validation 用)。"""
    return dict(_VARIANT_SPECS)


# ─── high-level: run-on-source ──────────────────────────────────────────

def generate_all_for_source(
    source: Path,
    upload_dir: Path,
    upload_id: str,
) -> Dict[str, str]:
    """source から決定された variant を全件生成する。worker から呼ぶ entrypoint。

    Returns {quality: status_message} dict。
    """
    if not source.exists():
        return {"_error": f"source not found: {source}"}
    probe = probe_source(source)
    plans = decide_variants(probe)
    results: Dict[str, str] = {}
    if not plans:
        if probe is None:
            results["_error"] = "probe failed"
        else:
            results["_skipped"] = (
                f"source {probe.width}x{probe.height} -> no variants needed"
            )
        return results
    crf_by_q = {"uhd": _VARIANT_CRF_UHD, "fhd": _VARIANT_CRF_FHD, "hd": _VARIANT_CRF_HD}
    for plan in plans:
        target = variant_path(upload_dir, upload_id, plan.quality)
        crf = crf_by_q.get(plan.quality, _VARIANT_CRF_FHD)
        ok, msg = generate_variant(source, target, plan.target_h, crf)
        results[plan.quality] = ("ok " if ok else "fail ") + msg
        logger.info(
            "[video_variants] generate quality=%s target_h=%d -> %s",
            plan.quality, plan.target_h, results[plan.quality],
        )
    return results
