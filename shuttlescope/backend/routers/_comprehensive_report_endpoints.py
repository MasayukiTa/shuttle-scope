"""包括レポート (JSON + PDF) のエンドポイント。

reports.py が大きいので別ファイルに切り出し、reports.py から router を共有して
追加 mount する設計。
"""
from __future__ import annotations

import io
import os
from datetime import datetime, date as DateType

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.auth import get_auth, check_export_player_scope
from backend.routers.reports import _safe_paragraph_text
from backend.services.comprehensive_report import gather_player_report


router = APIRouter(tags=["reports"])


def _parse_date(s: str | None) -> DateType | None:
    if not s:
        return None
    try:
        y, m, d = s.split("-")
        return DateType(int(y), int(m), int(d))
    except Exception:
        return None


@router.get("/reports/comprehensive")
def get_comprehensive_report_json(
    player_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tournament_level: str | None = Query(None),
):
    """包括解析レポート JSON (全 section + 試合単位データ込み)。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    return gather_player_report(
        db, player_id, ctx,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        tournament_level=tournament_level,
        include_per_match=True,
    )


@router.get("/reports/comprehensive_pdf")
def get_comprehensive_report_pdf(
    player_id: int,
    request: Request,
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    tournament_level: str | None = Query(None),
):
    """包括解析レポート PDF (試合単位は含まず、印刷向けに section ごとレンダ)。"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    data = gather_player_report(
        db, player_id, ctx,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        tournament_level=tournament_level,
        include_per_match=False,
    )
    if not data.get("success"):
        raise HTTPException(status_code=404, detail=data.get("error", "report failed"))
    pdf_bytes = _render_comprehensive_pdf(data)
    fname = f"comprehensive_player{player_id}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ─── PDF rendering ──────────────────────────────────────────────────

def _register_jp_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for font_path in [
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("ReportJP", font_path))
                return "ReportJP"
            except Exception:
                continue
    return "Helvetica"


def _fmt_cell(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) < 0.01 and v != 0:
            return f"{v:.4f}"
        return f"{v:.2f}"
    if isinstance(v, (dict, list)):
        s = str(v)
        return _safe_paragraph_text(s[:80] + ("…" if len(s) > 80 else ""))
    return _safe_paragraph_text(str(v))


def _kv_table(rows, font: str):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    t = Table(rows, colWidths=[40 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _render_section_data(flow, payload, h3, body, font: str, depth: int = 0):
    """汎用 walker。dict/list/primitive を section 内で表現。"""
    from reportlab.platypus import Paragraph, Table, TableStyle
    from reportlab.lib import colors

    if payload is None:
        flow.append(Paragraph("(データなし)", body))
        return

    # success/data wrap を剥がす
    if isinstance(payload, dict) and "success" in payload and "data" in payload:
        payload = payload.get("data", payload)

    if isinstance(payload, (str, int, float, bool)):
        flow.append(Paragraph(_safe_paragraph_text(str(payload)), body))
        return

    if isinstance(payload, list):
        if not payload:
            flow.append(Paragraph("(空)", body))
            return
        if all(isinstance(x, dict) for x in payload):
            cols: list[str] = []
            for x in payload[:30]:
                for k in x.keys():
                    if k not in cols:
                        cols.append(k)
                if len(cols) >= 6:
                    break
            cols = cols[:6]
            rows = [cols]
            for x in payload[:25]:
                rows.append([_fmt_cell(x.get(c)) for c in cols])
            if len(payload) > 25:
                tail = [f"... 残り {len(payload) - 25} 件"] + [""] * (len(cols) - 1)
                rows.append(tail)
            t = Table(rows, repeatRows=1)
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            flow.append(t)
            return
        flow.append(Paragraph(
            _safe_paragraph_text(", ".join(_fmt_cell(x) for x in payload[:80])),
            body,
        ))
        return

    if isinstance(payload, dict):
        if all(not isinstance(v, (dict, list)) for v in payload.values()):
            rows = [[_safe_paragraph_text(str(k)), _fmt_cell(v)] for k, v in payload.items()]
            flow.append(_kv_table(rows, font))
            return
        for k, v in payload.items():
            if depth == 0:
                flow.append(Paragraph(_safe_paragraph_text(str(k)), h3))
            else:
                flow.append(Paragraph(_safe_paragraph_text(f"・{k}"), body))
            _render_section_data(flow, v, h3, body, font, depth=depth + 1)
        return

    flow.append(Paragraph(_safe_paragraph_text(str(payload)), body))


_SECTION_LABELS = [
    ("descriptive", "1. 全体統計 (Descriptive)"),
    ("heatmap_hit", "2. 打点ヒートマップ"),
    ("heatmap_land", "3. 着地点ヒートマップ"),
    ("shot_types", "4. ショット種類分布"),
    ("shot_win_loss", "5. ショット別 勝敗"),
    ("set_comparison", "6. セット比較"),
    ("first_return", "7. ファーストリターン"),
    ("tournament_comparison", "8. 大会レベル別比較"),
    ("pre_win_patterns", "9. 勝利前ラリーパターン"),
    ("pre_loss_patterns", "10. 敗北前ラリーパターン"),
    ("rally_length_winrate", "11. ラリー長 × 勝率"),
    ("pressure_performance", "12. プレッシャー下のパフォーマンス"),
    ("shot_transition_matrix", "13. ショット遷移行列"),
    ("opponent_stats", "14. 対戦相手別統計"),
    ("temporal_performance", "15. 時系列パフォーマンス"),
    ("fatigue_risk", "16. 疲労リスク (coach/analyst のみ)"),
]


def _render_comprehensive_pdf(data: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    jp_font = _register_jp_font()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], fontName=jp_font, fontSize=18,
                            spaceAfter=8, alignment=0)
    h2 = ParagraphStyle("ReportH2", parent=styles["Heading2"], fontName=jp_font, fontSize=13,
                         spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1f2937"))
    h3 = ParagraphStyle("ReportH3", parent=styles["Heading3"], fontName=jp_font, fontSize=11,
                         spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#374151"))
    body = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontName=jp_font, fontSize=9,
                           leading=12)
    small = ParagraphStyle("ReportSmall", parent=styles["BodyText"], fontName=jp_font, fontSize=8,
                            leading=10, textColor=colors.HexColor("#6b7280"))
    err = ParagraphStyle("ReportErr", parent=body, textColor=colors.HexColor("#b91c1c"), fontSize=8)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title="ShuttleScope Comprehensive Report")
    flow = []

    header = data.get("header") or {}
    player = header.get("player") or {}
    flow.append(Paragraph(
        _safe_paragraph_text(f"包括解析レポート — {player.get('name', '')}"),
        title,
    ))
    flow.append(Paragraph(
        _safe_paragraph_text(
            f"生成: {header.get('generated_at_utc', '')} UTC ・ "
            f"閲覧ロール: {header.get('generated_for_role', '')} ・ "
            f"フィルタ: {header.get('filters', {})}"
        ),
        small,
    ))
    flow.append(Spacer(1, 4))

    flow.append(Paragraph("選手プロファイル", h2))
    profile_rows = [
        ["氏名", _safe_paragraph_text(player.get("name", ""))],
        ["氏名 (en)", _safe_paragraph_text(player.get("name_en") or "—")],
        ["所属", _safe_paragraph_text(player.get("team") or "—")],
        ["利き手", _safe_paragraph_text(player.get("dominant_hand") or "—")],
        ["生年", str(player.get("birth_year") or "—")],
    ]
    flow.append(_kv_table(profile_rows, jp_font))
    flow.append(Spacer(1, 6))

    sections = data.get("sections") or {}
    for key, label in _SECTION_LABELS:
        if key not in sections:
            continue
        sec = sections[key]
        flow.append(Paragraph(_safe_paragraph_text(label), h2))
        if not sec.get("ok"):
            flow.append(Paragraph(
                _safe_paragraph_text(f"(取得失敗: {sec.get('error', 'unknown')})"),
                err,
            ))
            continue
        _render_section_data(flow, sec.get("data"), h3, body, jp_font)
        flow.append(Spacer(1, 4))

    flow.append(Spacer(1, 8))
    flow.append(Paragraph(
        _safe_paragraph_text(
            "本レポートは ShuttleScope 自動生成。各 section の信頼度 (sample_size) を確認の上、"
            "コーチと選手の対話のたたき台としてください。試合単位の raw データは JSON 版を参照。"
        ),
        small,
    ))

    doc.build(flow)
    return buf.getvalue()
