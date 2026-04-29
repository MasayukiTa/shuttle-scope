"""領収書 / 適格請求書 PDF 生成サービス (Phase Pay-1 裏側機能)。

特徴:
  - reportlab ベース (既に requirements に入っている)
  - 事業者情報 / インボイス番号は **全て env (settings) から取得**
  - PDF にコード上の重要情報を一切書かない (定型文のみ)
  - 適格請求書の必須記載事項を満たす:
    1. 適格請求書発行事業者の氏名又は名称及び登録番号
    2. 取引年月日
    3. 取引内容 (軽減税率対象品目はその旨)
    4. 税率ごとに区分して合計した対価の額及び適用税率
    5. 税率ごとに区分した消費税額等
    6. 書類の交付を受ける事業者の氏名又は名称
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _settings():
    from backend.config import settings
    return settings


def _to_int_or_zero(value: Optional[float]) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _amount_breakdown(total_jpy: int, tax_rate: float) -> dict:
    """税込金額から税抜・消費税を算出する (内税方式)。"""
    if tax_rate <= 0:
        return {"net": total_jpy, "tax": 0, "gross": total_jpy, "rate": 0.0}
    # 内税: 税込 → 税抜 = 税込 / (1 + 税率)、消費税 = 税込 - 税抜
    net = round(total_jpy / (1 + tax_rate))
    tax = total_jpy - net
    return {"net": net, "tax": tax, "gross": total_jpy, "rate": tax_rate}


def is_qualified_invoice() -> bool:
    """インボイス番号が設定されていれば適格請求書として発行可能。"""
    s = _settings()
    return bool((getattr(s, "ss_invoice_registration_number", "") or "").strip())


def generate_receipt_pdf(
    *,
    order_public_id: str,
    issued_at: datetime,
    customer_display: str,         # ユーザ宛名 (display_name または email)
    product_name: str,
    amount_jpy: int,
    payment_method_label: str,
    paid_at: Optional[datetime] = None,
) -> bytes:
    """領収書 PDF を生成して bytes で返す。"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(f"reportlab が必要です: {exc}")

    # 日本語フォント (CID フォント、別途フォントファイル不要)
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        font_name = "HeiseiKakuGo-W5"
    except Exception:
        font_name = "Helvetica"

    s = _settings()
    company = (getattr(s, "ss_legal_company_name", "") or "").strip() or "(事業者名未設定)"
    representative = (getattr(s, "ss_legal_representative", "") or "").strip()
    address = (getattr(s, "ss_legal_address", "") or "").strip() or "(住所未設定)"
    phone = (getattr(s, "ss_legal_phone", "") or "").strip()
    email = (getattr(s, "ss_legal_email", "") or "").strip() or "support@shuttle-scope.com"
    invoice_no = (getattr(s, "ss_invoice_registration_number", "") or "").strip()
    tax_rate = float(getattr(s, "ss_consumption_tax_rate", 0.10) or 0.10)

    breakdown = _amount_breakdown(amount_jpy, tax_rate)

    title = "適格請求書 兼 領収書" if invoice_no else "領収書"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle("h", parent=styles["Heading1"], fontName=font_name, fontSize=18, leading=24)
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=styles["Normal"], fontName=font_name, fontSize=8, leading=11, textColor=colors.grey)

    story = []
    story.append(Paragraph(title, h_style))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(f"発行日: {issued_at.strftime('%Y年%m月%d日')}", body))
    story.append(Paragraph(f"領収書番号: {order_public_id}", body))
    if invoice_no:
        story.append(Paragraph(f"適格請求書発行事業者登録番号: {invoice_no}", body))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(f"<b>{customer_display}</b> 様", body))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("下記のとおりお支払いを受領いたしました。", body))
    story.append(Spacer(1, 6 * mm))

    # 明細表
    detail_data = [
        ["品目", "数量", "金額 (税込)"],
        [product_name, "1", f"¥{amount_jpy:,}"],
    ]
    detail_table = Table(detail_data, colWidths=[100 * mm, 25 * mm, 45 * mm])
    detail_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font_name, 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 6 * mm))

    # 税率内訳 (適格請求書の必須項目)
    tax_data = [
        ["税率", "対象金額 (税抜)", "消費税"],
        [f"{int(breakdown['rate'] * 100)}%", f"¥{breakdown['net']:,}", f"¥{breakdown['tax']:,}"],
        ["合計 (税込)", "", f"¥{breakdown['gross']:,}"],
    ]
    tax_table = Table(tax_data, colWidths=[40 * mm, 60 * mm, 70 * mm])
    tax_table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font_name, 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("BACKGROUND", (0, -1), (-1, -1), colors.lightblue),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONT", (0, -1), (-1, -1), font_name, 11),
    ]))
    story.append(tax_table)
    story.append(Spacer(1, 6 * mm))

    pay_info = [
        f"決済手段: {payment_method_label}",
    ]
    if paid_at:
        pay_info.append(f"決済日時: {paid_at.strftime('%Y年%m月%d日 %H:%M:%S')}")
    for line in pay_info:
        story.append(Paragraph(line, body))
    story.append(Spacer(1, 12 * mm))

    # 発行者情報
    story.append(Paragraph("<b>発行者</b>", body))
    issuer_lines = [company]
    if representative:
        issuer_lines.append(f"代表: {representative}")
    issuer_lines.append(address)
    if phone:
        issuer_lines.append(f"TEL: {phone}")
    issuer_lines.append(f"Email: {email}")
    if invoice_no:
        issuer_lines.append(f"登録番号: {invoice_no}")
    for line in issuer_lines:
        story.append(Paragraph(line, body))

    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph(
        "本書類は電子的に発行された領収書です。" + (" 適格請求書の要件を満たしています。" if invoice_no else ""),
        small,
    ))

    doc.build(story)
    return buf.getvalue()
