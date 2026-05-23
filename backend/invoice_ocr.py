"""Invoice-specific OCR post-processing.

Inspired by Gandedong/audit-python- '批量读取pdf发票后汇总'.
Extracts structured invoice fields from OCR text.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Invoice field patterns ────────────────────────────────────────
INVOICE_PATTERNS = {
    "invoice_code": re.compile(r"发票代码[：:\s]*([\d]{10,12})"),
    "invoice_no": re.compile(r"发票号码[：:\s]*([\d]{8})"),
    "invoice_date": re.compile(r"开票日期[：:\s]*(20\d{2})[年\s-]*(\d{1,2})[月\s-]*(\d{1,2})"),
    "seller_name": re.compile(r"销售方名称[：:\s]*([^\n]{2,60})"),
    "seller_tax_id": re.compile(r"销售方纳税人识别号[：:\s]*([\dA-Z]{15,20})"),
    "buyer_name": re.compile(r"购买方名称[：:\s]*([^\n]{2,60})"),
    "buyer_tax_id": re.compile(r"购买方纳税人识别号[：:\s]*([\dA-Z]{15,20})"),
    "total_amount": re.compile(r"合计金额[：:\s]*[¥￥]?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"),
    "total_tax": re.compile(r"合计税额[：:\s]*[¥￥]?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"),
    "grand_total": re.compile(r"价税合计[：:\s(小写)]*[¥￥]?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)"),
}

AMOUNT_CLEAN = re.compile(r"[¥￥,，\s]")


def extract_invoice_fields(text: str) -> dict[str, Any]:
    """Extract structured invoice fields from OCR text."""
    result: dict[str, Any] = {"raw_text": text[:1000], "extracted_at": datetime.utcnow().isoformat()}

    for field, pattern in INVOICE_PATTERNS.items():
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if field.endswith("_amount") or field in {"total_amount", "total_tax", "grand_total"}:
                value = AMOUNT_CLEAN.sub("", value)
                try:
                    result[field] = float(value)
                except ValueError:
                    result[field] = value
            elif field == "invoice_date":
                try:
                    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    result[field] = date(y, m, d).isoformat()
                except (ValueError, IndexError):
                    result[field] = match.group(0)
            else:
                result[field] = value

    # Validation
    result["is_valid"] = bool(
        result.get("invoice_code") and result.get("invoice_no") and result.get("grand_total")
    )
    if result["is_valid"]:
        result["confidence"] = 0.85
    elif result.get("invoice_code") or result.get("invoice_no"):
        result["confidence"] = 0.6
    else:
        result["confidence"] = 0.3

    return result


def batch_extract_invoices(
    ocr_texts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract invoice fields from multiple OCR results."""
    invoices = []
    for item in ocr_texts:
        text = item.get("raw_text", "") or item.get("text", "")
        if not text:
            continue
        invoice = extract_invoice_fields(text)
        invoice["source_id"] = item.get("id", "")
        invoice["source_page"] = item.get("page_no", 1)
        invoices.append(invoice)
    return invoices


def export_invoice_summary(invoices: list[dict[str, Any]], fmt: str = "excel") -> str:
    """Export extracted invoice data to file."""
    from pathlib import Path

    from .settings import EXPORT_DIR

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    headers = [
        "发票代码", "发票号码", "开票日期", "销售方名称", "销售方税号",
        "购买方名称", "购买方税号", "合计金额", "合计税额", "价税合计", "是否有效", "置信度",
    ]

    if fmt == "csv":
        path = EXPORT_DIR / f"invoices_{timestamp}.csv"
        import csv
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            for inv in invoices:
                writer.writerow([
                    inv.get("invoice_code", ""), inv.get("invoice_no", ""), inv.get("invoice_date", ""),
                    inv.get("seller_name", ""), inv.get("seller_tax_id", ""),
                    inv.get("buyer_name", ""), inv.get("buyer_tax_id", ""),
                    inv.get("total_amount", ""), inv.get("total_tax", ""), inv.get("grand_total", ""),
                    "是" if inv.get("is_valid") else "否", inv.get("confidence", ""),
                ])
        return str(path)

    try:
        from openpyxl import Workbook
        path = EXPORT_DIR / f"invoices_{timestamp}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "发票汇总"
        ws.append(headers)
        for inv in invoices:
            ws.append([
                inv.get("invoice_code", ""), inv.get("invoice_no", ""), inv.get("invoice_date", ""),
                inv.get("seller_name", ""), inv.get("seller_tax_id", ""),
                inv.get("buyer_name", ""), inv.get("buyer_tax_id", ""),
                inv.get("total_amount", ""), inv.get("total_tax", ""), inv.get("grand_total", ""),
                "是" if inv.get("is_valid") else "否", inv.get("confidence", ""),
            ])
        wb.save(path)
        return str(path)
    except Exception:
        return export_invoice_summary(invoices, fmt="csv")
