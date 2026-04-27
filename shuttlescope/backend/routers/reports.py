"""レポートAPI（/api/reports）"""
import io
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, Player, Condition
from backend.utils.auth import check_export_player_scope, get_auth
from backend.utils.confidence import check_confidence

# matplotlib は使用時に遅延ロード（起動時間短縮のため）
_matplotlib_initialized = False
_MATPLOTLIB_AVAILABLE: bool | None = None
_JP_FONT: str | None = None


def _ensure_matplotlib() -> bool:
    """matplotlib が利用可能かチェックし、初回のみロードする"""
    global _matplotlib_initialized, _MATPLOTLIB_AVAILABLE, _JP_FONT
    if _matplotlib_initialized:
        return bool(_MATPLOTLIB_AVAILABLE)
    _matplotlib_initialized = True
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.font_manager as _fm
        import os

        # 日本語フォントを設定（Windows: Meiryo / Linux: Noto Sans CJK）
        _JP_FONT = None
        for _candidate in ["Meiryo", "MS Gothic", "Noto Sans CJK JP", "IPAGothic"]:
            try:
                _fp = _fm.findfont(_fm.FontProperties(family=_candidate), fallback_to_default=False)
                if _fp and "DejaVu" not in _fp:
                    _JP_FONT = _candidate
                    break
            except Exception:
                pass
        if _JP_FONT is None:
            _meiryo = "C:/Windows/Fonts/meiryo.ttc"
            if os.path.exists(_meiryo):
                _fm.fontManager.addfont(_meiryo)
                _JP_FONT = "Meiryo"

        _MATPLOTLIB_AVAILABLE = True
    except ImportError:
        _MATPLOTLIB_AVAILABLE = False
    return bool(_MATPLOTLIB_AVAILABLE)

router = APIRouter()

# 禁止ワードと置換ワードのマッピング（選手向けテキスト用）
FORBIDDEN_WORDS = {
    "弱点": "伸びしろ",
    "苦手": "成長エリア",
    "悪い": "改善余地がある",
    "負け": "課題のある",
    "失敗": "学びのある",
}

DISCLAIMER_JA = "このデータは相関を示すものであり、因果関係を示すものではありません"


def _build_court_heatmap_png(zone_counts: dict[str, int]) -> bytes | None:
    """コートゾーン別ヒートマップをmatplotlibでPNG生成する"""
    if not _ensure_matplotlib():
        return None

    import matplotlib.pyplot as plt
    import numpy as np

    # 9ゾーンのグリッド配置（行=奥→手前, 列=左→右）
    ZONES = [
        ["BL", "BC", "BR"],
        ["ML", "MC", "MR"],
        ["NL", "NC", "NR"],
    ]
    ZONE_LABELS_JA = {
        "BL": "バック左", "BC": "バック中", "BR": "バック右",
        "ML": "ミドル左", "MC": "ミドル中", "MR": "ミドル右",
        "NL": "ネット左", "NC": "ネット中", "NR": "ネット右",
    }

    data = np.zeros((3, 3), dtype=float)
    for r, row in enumerate(ZONES):
        for c, zone in enumerate(row):
            data[r][c] = zone_counts.get(zone, 0)

    fig, ax = plt.subplots(figsize=(4, 3), facecolor="#1f2937")
    ax.set_facecolor("#1f2937")

    ax.imshow(data, cmap="coolwarm", vmin=0, vmax=max(data.max(), 1))

    font_kwargs = {"fontfamily": _JP_FONT} if _JP_FONT else {}
    for r in range(3):
        for c in range(3):
            zone = ZONES[r][c]
            count = int(data[r][c])
            label = ZONE_LABELS_JA.get(zone, zone) if _JP_FONT else zone
            ax.text(c, r, f"{label}\n{count}",
                    ha="center", va="center", fontsize=8, color="white",
                    **font_kwargs)

    ax.set_xticks([])
    ax.set_yticks([])
    title = "打点分布ヒートマップ" if _JP_FONT else "Hit Zone Heatmap"
    ax.set_title(title, color="white", fontsize=9, pad=6,
                 **({"fontfamily": _JP_FONT} if _JP_FONT else {}))

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def sanitize_player_text(text: str) -> str:
    """選手向けテキストから禁止ワードを除去・置換する"""
    for k, v in FORBIDDEN_WORDS.items():
        text = text.replace(k, v)
    return text


def _player_role_in_match(match: Match, player_id: int) -> str | None:
    """プレイヤーIDに対応するロール (player_a / player_b) を返す"""
    if match.player_a_id == player_id:
        return "player_a"
    if match.player_b_id == player_id:
        return "player_b"
    return None


# ---------------------------------------------------------------------------
# I-001: スカウティングレポート（PDF or JSON）
# ---------------------------------------------------------------------------

@router.get("/reports/scouting")
def get_scouting_report(player_id: int, request: Request, db: Session = Depends(get_db)):
    """I-001: スカウティングレポートを生成する（reportlab があればPDF）。
    player は自分のみ、coach は同チーム選手のみ閲覧可能（analyst / admin は無制限）。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": f"選手ID {player_id} が見つかりません"}

    # 基本統計の収集
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

    role_by_match = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }
    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_ids = [s.id for s in sets]
    set_to_match = {s.id: s.match_id for s in sets}
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    total_rallies = len(rallies)
    wins = 0
    total_length = 0
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        if rally.winner == role:
            wins += 1
        total_length += rally.rally_length

    win_rate = round(wins / total_rallies, 3) if total_rallies else 0.0
    avg_rally = round(total_length / total_rallies, 2) if total_rallies else 0.0
    confidence = check_confidence("descriptive_basic", total_rallies)

    # ショット集計
    rally_ids = [r.id for r in rallies]
    rally_to_role = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        rally_to_role[rally.id] = role_by_match[match_id]

    shot_counter: dict[str, int] = defaultdict(int)
    zone_counts: dict[str, int] = defaultdict(int)
    if rally_ids:
        strokes = db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all()
        for stroke in strokes:
            role = rally_to_role.get(stroke.rally_id)
            if stroke.player == role:
                shot_counter[stroke.shot_type] += 1
                if stroke.hit_zone:
                    zone_counts[stroke.hit_zone] += 1

    top_shots = sorted(
        [{"shot_type": st, "count": cnt} for st, cnt in shot_counter.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:5]

    # コートヒートマップ PNG 生成（matplotlib）
    heatmap_png = _build_court_heatmap_png(dict(zone_counts))

    # reportlab を使用してPDFを生成
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
        styles = getSampleStyleSheet()

        # フォント設定（日本語対応のため既存フォントを流用）
        # システムフォントが利用不可の場合は英語フォールバック
        try:
            pdfmetrics.registerFont(TTFont("Meiryo", "C:/Windows/Fonts/meiryo.ttc"))
            jp_font = "Meiryo"
        except Exception:
            jp_font = "Helvetica"

        title_style = ParagraphStyle(
            "Title", fontName=jp_font, fontSize=16, spaceAfter=10
        )
        body_style = ParagraphStyle(
            "Body", fontName=jp_font, fontSize=10, spaceAfter=6
        )
        footer_style = ParagraphStyle(
            "Footer", fontName=jp_font, fontSize=8, textColor=colors.grey
        )

        content = []
        content.append(Paragraph(f"スカウティングレポート: {player.name}", title_style))
        content.append(Spacer(1, 5*mm))

        # 信頼度バッジ相当テキスト
        content.append(Paragraph(
            f"信頼度: {confidence['stars']} {confidence['label']} (サンプル: {total_rallies}ラリー)",
            body_style
        ))
        content.append(Spacer(1, 3*mm))

        # 基本統計
        stats_data = [
            ["項目", "値"],
            ["試合数", str(len(matches))],
            ["総ラリー数", str(total_rallies)],
            ["勝率", f"{win_rate:.1%}"],
            ["平均ラリー長", f"{avg_rally:.1f}打"],
        ]
        table = Table(stats_data, colWidths=[60*mm, 60*mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), jp_font),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ]))
        content.append(table)
        content.append(Spacer(1, 5*mm))

        # 主要ショット
        content.append(Paragraph("主要ショット", body_style))
        shot_data = [["ショット種別", "打数"]] + [
            [s["shot_type"], str(s["count"])] for s in top_shots
        ]
        shot_table = Table(shot_data, colWidths=[60*mm, 60*mm])
        shot_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), jp_font),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        content.append(shot_table)
        content.append(Spacer(1, 5*mm))

        # コートヒートマップ画像（matplotlib生成）
        if heatmap_png:
            img_buf = io.BytesIO(heatmap_png)
            img = Image(img_buf, width=80*mm, height=60*mm)
            content.append(img)
            content.append(Spacer(1, 5*mm))

        content.append(Spacer(1, 10*mm))

        # 免責事項フッター
        content.append(Paragraph(DISCLAIMER_JA, footer_style))
        content.append(Paragraph(
            f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}", footer_style
        ))

        doc.build(content)
        pdf_bytes = buf.getvalue()

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=scouting_{player_id}.pdf"},
        )

    except Exception:
        # reportlab 利用不可またはエラー: JSON でフォールバック
        return {
            "success": True,
            "data": {
                "player_name": player.name,
                "total_matches": len(matches),
                "total_rallies": total_rallies,
                "win_rate": win_rate,
                "avg_rally_length": avg_rally,
                "top_shots": top_shots,
                "disclaimer": DISCLAIMER_JA,
            },
            "meta": {"sample_size": total_rallies, "confidence": confidence},
        }


# ---------------------------------------------------------------------------
# I-002: 選手成長レポート
# ---------------------------------------------------------------------------

@router.get("/reports/player_growth")
def get_player_growth_report(player_id: int, request: Request, db: Session = Depends(get_db)):
    """I-002: 選手向けの成長レポートを生成する（禁止ワードをサニタイズ済み）。
    player は自分のみ、coach は同チーム選手のみ閲覧可能。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": f"選手ID {player_id} が見つかりません"}

    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

    role_by_match = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }
    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_ids = [s.id for s in sets]
    set_to_match = {s.id: s.match_id for s in sets}
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    total_rallies = len(rallies)
    wins = 0
    total_length = 0
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        if rally.winner == role:
            wins += 1
        total_length += rally.rally_length

    win_rate = round(wins / total_rallies, 3) if total_rallies else 0.0
    avg_rally = round(total_length / total_rallies, 2) if total_rallies else 0.0
    confidence = check_confidence("descriptive_basic", total_rallies)

    # 成長メッセージ生成（禁止ワード不使用）
    if total_rallies == 0:
        growth_message = sanitize_player_text("データ蓄積中です。試合後にアノテーションを完了させてください。")
    elif win_rate >= 0.6:
        growth_message = sanitize_player_text("安定した成果を出せています。さらなる伸びしろを探してみましょう。")
    elif win_rate >= 0.4:
        growth_message = sanitize_player_text("バランスの取れた成長エリアがあります。継続的な練習が大切です。")
    else:
        growth_message = sanitize_player_text("学びのある経験から成長できます。伸びしろに注目しましょう。")

    # ストローク傾向
    rally_ids = [r.id for r in rallies]
    rally_to_role = {
        r.id: role_by_match[set_to_match[r.set_id]] for r in rallies
    }

    shot_counter: dict[str, int] = defaultdict(int)
    if rally_ids:
        strokes = db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all()
        for stroke in strokes:
            role = rally_to_role.get(stroke.rally_id)
            if stroke.player == role:
                shot_counter[stroke.shot_type] += 1

    top_shots = sorted(
        [{"shot_type": st, "count": cnt} for st, cnt in shot_counter.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:3]

    # 全テキストをサニタイズ
    safe_message = sanitize_player_text(growth_message)
    safe_player_name = sanitize_player_text(player.name)

    return {
        "success": True,
        "data": {
            "player_name": safe_player_name,
            "growth_message": safe_message,
            "total_matches": len(matches),
            "total_rallies": total_rallies,
            "win_rate": win_rate,
            "avg_rally_length": avg_rally,
            "top_shots": top_shots,
            "disclaimer": sanitize_player_text(DISCLAIMER_JA),
        },
        "meta": {"sample_size": total_rallies, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# I-003: セット間速報レポート（JSON, <30s）
# ---------------------------------------------------------------------------

@router.get("/reports/interval_flash")
def get_interval_flash_report(
    match_id: int,
    completed_set_num: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """I-003: セット間の速報レポートをJSON形式で返す（応答時間<30秒）"""
    match = db.get(Match, match_id)
    if not match:
        return {"success": False, "error": f"試合ID {match_id} が見つかりません"}

    # 完了済みセットを取得
    completed_sets = (
        db.query(GameSet)
        .filter(
            GameSet.match_id == match_id,
            GameSet.set_num <= completed_set_num,
        )
        .order_by(GameSet.set_num)
        .all()
    )

    if not completed_sets:
        confidence = check_confidence("descriptive_basic", 0)
        return {
            "success": True,
            "data": {
                "match_id": match_id,
                "completed_set_num": completed_set_num,
                "set_scores": [],
                "current_leader": None,
                "disclaimer": DISCLAIMER_JA,
            },
            "meta": {"sample_size": 0, "confidence": confidence},
        }

    set_ids = [s.id for s in completed_sets]
    rallies_all = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    )

    # セットごとのスコアサマリー
    set_scores = []
    a_sets = 0
    b_sets = 0
    total_rallies = 0

    for game_set in completed_sets:
        set_rallies = [r for r in rallies_all if r.set_id == game_set.id]
        total_rallies += len(set_rallies)
        a_wins = sum(1 for r in set_rallies if r.winner == "player_a")
        b_wins = len(set_rallies) - a_wins

        if game_set.winner == "player_a":
            a_sets += 1
        elif game_set.winner == "player_b":
            b_sets += 1

        set_scores.append({
            "set_num": game_set.set_num,
            "score_a": game_set.score_a,
            "score_b": game_set.score_b,
            "winner": game_set.winner,
            "rally_wins_a": a_wins,
            "rally_wins_b": b_wins,
        })

    current_leader = None
    if a_sets > b_sets:
        current_leader = "player_a"
    elif b_sets > a_sets:
        current_leader = "player_b"

    confidence = check_confidence("descriptive_basic", total_rallies)

    return {
        "success": True,
        "data": {
            "match_id": match_id,
            "completed_set_num": completed_set_num,
            "set_scores": set_scores,
            "sets_a": a_sets,
            "sets_b": b_sets,
            "current_leader": current_leader,
            "disclaimer": DISCLAIMER_JA,
        },
        "meta": {"sample_size": total_rallies, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# I-004: 体調レポート JSON
# ---------------------------------------------------------------------------

@router.get("/reports/condition")
def get_condition_report(
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """I-004: 選手の体調データをJSON形式でエクスポートする。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": f"選手ID {player_id} が見つかりません"}

    conditions = (
        db.query(Condition)
        .filter(Condition.player_id == player_id)
        .order_by(Condition.measured_at.desc())
        .limit(120)
        .all()
    )

    rows = [
        {
            "measured_at": str(c.measured_at),
            "condition_type": c.condition_type,
            "ccs_score": c.ccs_score,
            "hooper_index": c.hooper_index,
            "session_rpe": c.session_rpe,
            "sleep_hours": c.sleep_hours,
            "weight_kg": c.weight_kg,
            "f1_physical": c.f1_physical,
            "f2_stress": c.f2_stress,
            "f3_mood": c.f3_mood,
            "f4_motivation": c.f4_motivation,
            "f5_sleep_life": c.f5_sleep_life,
        }
        for c in conditions
    ]

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    summary = {
        "record_count": len(rows),
        "date_from": rows[-1]["measured_at"] if rows else None,
        "date_to": rows[0]["measured_at"] if rows else None,
        "avg_ccs": _avg([r["ccs_score"] for r in rows]),
        "avg_hooper": _avg([r["hooper_index"] for r in rows]),
        "avg_rpe": _avg([r["session_rpe"] for r in rows]),
        "avg_sleep_h": _avg([r["sleep_hours"] for r in rows]),
    }

    return {
        "success": True,
        "data": {
            "player_name": player.name,
            "summary": summary,
            "records": rows,
            "disclaimer": DISCLAIMER_JA,
        },
        "meta": {"sample_size": len(rows), "confidence": check_confidence("descriptive_basic", len(rows))},
    }


# ---------------------------------------------------------------------------
# I-005: 体調レポート PDF
# ---------------------------------------------------------------------------

@router.get("/reports/condition_pdf")
def get_condition_report_pdf(
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """I-005: 選手の体調サマリーをPDF形式でエクスポートする。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": f"選手ID {player_id} が見つかりません"}

    conditions = (
        db.query(Condition)
        .filter(Condition.player_id == player_id)
        .order_by(Condition.measured_at.desc())
        .limit(60)
        .all()
    )

    def _avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 2) if v else None

    avg_ccs = _avg([c.ccs_score for c in conditions])
    avg_hooper = _avg([c.hooper_index for c in conditions])
    avg_rpe = _avg([c.session_rpe for c in conditions])
    avg_sleep = _avg([c.sleep_hours for c in conditions])
    date_from = str(conditions[-1].measured_at) if conditions else "—"
    date_to = str(conditions[0].measured_at) if conditions else "—"

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
        try:
            pdfmetrics.registerFont(TTFont("Meiryo", "C:/Windows/Fonts/meiryo.ttc"))
            jp = "Meiryo"
        except Exception:
            jp = "Helvetica"

        title_s = ParagraphStyle("T", fontName=jp, fontSize=16, spaceAfter=8)
        body_s = ParagraphStyle("B", fontName=jp, fontSize=10, spaceAfter=5)
        footer_s = ParagraphStyle("F", fontName=jp, fontSize=8, textColor=colors.grey)

        content = [
            Paragraph(f"体調レポート: {player.name}", title_s),
            Paragraph(f"集計期間: {date_from} 〜 {date_to}　記録数: {len(conditions)}", body_s),
            Spacer(1, 5*mm),
            Paragraph("■ 平均指標", body_s),
        ]
        tbl = Table(
            [
                ["指標", "平均値"],
                ["CCS スコア", str(avg_ccs) if avg_ccs is not None else "—"],
                ["Hooper Index", str(avg_hooper) if avg_hooper is not None else "—"],
                ["セッション RPE", str(avg_rpe) if avg_rpe is not None else "—"],
                ["睡眠時間 (h)", str(avg_sleep) if avg_sleep is not None else "—"],
            ],
            colWidths=[80*mm, 60*mm],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), jp),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        content.append(tbl)

        if conditions:
            content.append(Spacer(1, 5*mm))
            content.append(Paragraph("■ 直近20件の記録", body_s))
            rec_data = [["測定日", "種別", "CCS", "Hooper", "RPE", "睡眠(h)"]]
            for c in conditions[:20]:
                rec_data.append([
                    str(c.measured_at), c.condition_type or "—",
                    f"{c.ccs_score:.1f}" if c.ccs_score is not None else "—",
                    str(c.hooper_index) if c.hooper_index is not None else "—",
                    str(c.session_rpe) if c.session_rpe is not None else "—",
                    f"{c.sleep_hours:.1f}" if c.sleep_hours is not None else "—",
                ])
            rec_tbl = Table(rec_data, colWidths=[30*mm, 25*mm, 22*mm, 22*mm, 20*mm, 20*mm])
            rec_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0891b2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), jp),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            content.append(rec_tbl)

        content.append(Spacer(1, 8*mm))
        content.append(Paragraph(DISCLAIMER_JA, footer_s))
        content.append(Paragraph(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}", footer_s))
        doc.build(content)
        return Response(
            content=buf.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=condition_{player_id}.pdf"},
        )

    except Exception:
        return {
            "success": True,
            "data": {
                "player_name": player.name,
                "summary": {
                    "record_count": len(conditions), "date_from": date_from, "date_to": date_to,
                    "avg_ccs": avg_ccs, "avg_hooper": avg_hooper, "avg_rpe": avg_rpe, "avg_sleep_h": avg_sleep,
                },
                "disclaimer": DISCLAIMER_JA,
            },
        }


# ---------------------------------------------------------------------------
# I-006: 予測レポート JSON
# ---------------------------------------------------------------------------

@router.get("/reports/prediction")
def get_prediction_report(
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """I-006: 選手の予測データをJSON形式でエクスポートする。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": f"選手ID {player_id} が見つかりません"}

    matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .order_by(Match.date.desc())
        .limit(30)
        .all()
    )
    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    total = len(rallies)
    wins = sum(1 for r in rallies if r.winner == role_by_match.get(set_to_match.get(r.set_id)))
    win_rate = round(wins / total, 3) if total else None

    levels: dict = {}
    for m in matches:
        lv = m.tournament_level or "不明"
        role = role_by_match[m.id]
        m_ids = {r.id for r in rallies if set_to_match.get(r.set_id) == m.id}
        m_wins = sum(1 for r in rallies if r.id in m_ids and r.winner == role)
        if lv not in levels:
            levels[lv] = {"wins": 0, "total": 0}
        levels[lv]["wins"] += m_wins
        levels[lv]["total"] += len(m_ids)

    recent_conditions = (
        db.query(Condition)
        .filter(Condition.player_id == player_id)
        .order_by(Condition.measured_at.desc())
        .limit(4)
        .all()
    )
    hoopers = [c.hooper_index for c in recent_conditions if c.hooper_index is not None]
    fatigue = round(sum(hoopers) / len(hoopers), 1) if hoopers else None

    return {
        "success": True,
        "data": {
            "player_name": player.name,
            "overall": {"total_matches": len(matches), "total_rallies": total, "win_rate": win_rate},
            "by_level": [
                {"level": lv, "win_rate": round(v["wins"] / v["total"], 3) if v["total"] else None, "rallies": v["total"]}
                for lv, v in levels.items()
            ],
            "fatigue_hooper_avg_recent4": fatigue,
            "disclaimer": DISCLAIMER_JA,
        },
        "meta": {"sample_size": total, "confidence": check_confidence("descriptive_basic", total)},
    }


# ---------------------------------------------------------------------------
# I-007: 予測レポート PDF
# ---------------------------------------------------------------------------

@router.get("/reports/prediction_pdf")
def get_prediction_report_pdf(
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """I-007: 選手の予測サマリーをPDF形式でエクスポートする。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    player = db.get(Player, player_id)
    if not player:
        return {"success": False, "error": f"選手ID {player_id} が見つかりません"}

    matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .order_by(Match.date.desc())
        .limit(30)
        .all()
    )
    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    total = len(rallies)
    wins = sum(1 for r in rallies if r.winner == role_by_match.get(set_to_match.get(r.set_id)))
    win_rate_pct = round(wins / total * 100, 1) if total else None

    levels: dict = {}
    for m in matches:
        lv = m.tournament_level or "不明"
        role = role_by_match[m.id]
        m_ids = {r.id for r in rallies if set_to_match.get(r.set_id) == m.id}
        m_wins = sum(1 for r in rallies if r.id in m_ids and r.winner == role)
        if lv not in levels:
            levels[lv] = {"wins": 0, "total": 0}
        levels[lv]["wins"] += m_wins
        levels[lv]["total"] += len(m_ids)

    recent_conditions = (
        db.query(Condition)
        .filter(Condition.player_id == player_id)
        .order_by(Condition.measured_at.desc())
        .limit(4)
        .all()
    )
    hoopers = [c.hooper_index for c in recent_conditions if c.hooper_index is not None]
    fatigue = round(sum(hoopers) / len(hoopers), 1) if hoopers else None

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
        try:
            pdfmetrics.registerFont(TTFont("Meiryo", "C:/Windows/Fonts/meiryo.ttc"))
            jp = "Meiryo"
        except Exception:
            jp = "Helvetica"

        title_s = ParagraphStyle("T", fontName=jp, fontSize=16, spaceAfter=8)
        body_s = ParagraphStyle("B", fontName=jp, fontSize=10, spaceAfter=5)
        footer_s = ParagraphStyle("F", fontName=jp, fontSize=8, textColor=colors.grey)

        content = [
            Paragraph(f"予測レポート: {player.name}", title_s),
            Paragraph(f"直近 {len(matches)} 試合 / {total} ラリー 分析", body_s),
            Spacer(1, 5*mm),
            Paragraph("■ 総合成績", body_s),
        ]
        overall_tbl = Table(
            [
                ["項目", "値"],
                ["試合数", str(len(matches))],
                ["ラリー数", str(total)],
                ["ラリー勝率", f"{win_rate_pct}%" if win_rate_pct is not None else "—"],
                ["疲労 Hooper (直近4回平均)", str(fatigue) if fatigue is not None else "—"],
            ],
            colWidths=[80*mm, 60*mm],
        )
        overall_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), jp),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        content.append(overall_tbl)

        if levels:
            content.append(Spacer(1, 5*mm))
            content.append(Paragraph("■ 大会レベル別勝率", body_s))
            lv_data = [["大会レベル", "ラリー勝率", "ラリー数"]]
            for lv, v in sorted(levels.items()):
                wr = round(v["wins"] / v["total"] * 100, 1) if v["total"] else None
                lv_data.append([lv, f"{wr}%" if wr is not None else "—", str(v["total"])])
            lv_tbl = Table(lv_data, colWidths=[60*mm, 45*mm, 35*mm])
            lv_tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0891b2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), jp),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            content.append(lv_tbl)

        content.append(Spacer(1, 8*mm))
        content.append(Paragraph(DISCLAIMER_JA, footer_s))
        content.append(Paragraph(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}", footer_s))
        doc.build(content)
        return Response(
            content=buf.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=prediction_{player_id}.pdf"},
        )

    except Exception:
        return {
            "success": True,
            "data": {
                "player_name": player.name,
                "total_matches": len(matches),
                "total_rallies": total,
                "win_rate_pct": win_rate_pct,
                "fatigue_hooper_avg_recent4": fatigue,
                "disclaimer": DISCLAIMER_JA,
            },
        }
