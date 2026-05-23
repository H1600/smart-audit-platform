"""Bank statement reconciliation and format standardization.

Inspired by Gandedong/audit-python- '统一各个银行的对账单'.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LedgerRecord

logger = logging.getLogger(__name__)

# ── Bank format templates ─────────────────────────────────────────
BANK_TEMPLATES = {
    "icbc": {
        "name": "工商银行",
        "date_col": ["交易日期", "记账日期", "date"],
        "amount_in": ["收入金额", "贷方金额", "收入"],
        "amount_out": ["支出金额", "借方金额", "支出"],
        "counterparty": ["对方户名", "对方名称", "对方"],
        "summary": ["摘要", "用途", "备注", "remark"],
        "balance": ["余额", "balance"],
    },
    "ccb": {
        "name": "建设银行",
        "date_col": ["交易日期", "date"],
        "amount_in": ["收入金额", "贷方发生额", "收入"],
        "amount_out": ["支出金额", "借方发生额", "支出"],
        "counterparty": ["对方户名", "对方名称"],
        "summary": ["摘要", "用途", "备注"],
        "balance": ["余额"],
    },
    "abc": {
        "name": "农业银行",
        "date_col": ["交易日期", "date"],
        "amount_in": ["收入金额", "贷方金额"],
        "amount_out": ["支出金额", "借方金额"],
        "counterparty": ["对方户名", "对方名称"],
        "summary": ["摘要", "用途", "备注"],
        "balance": ["余额"],
    },
    "boc": {
        "name": "中国银行",
        "date_col": ["交易日期", "记账日期"],
        "amount_in": ["收入金额", "贷方金额"],
        "amount_out": ["支出金额", "借方金额"],
        "counterparty": ["对方户名", "对方名称"],
        "summary": ["摘要", "用途"],
        "balance": ["余额"],
    },
}

DATE_RE = re.compile(r"(20\d{2}|19\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
AMOUNT_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


def detect_bank_template(headers: list[str]) -> str | None:
    """Auto-detect bank template from headers."""
    header_lower = [h.lower().replace(" ", "") for h in headers]
    best_score = 0
    best_bank: str | None = None
    for bank_id, template in BANK_TEMPLATES.items():
        score = 0
        for field_list in template.values():
            if isinstance(field_list, list):
                if any(h in header_lower for h in field_list for h_lower in [h.lower().replace(" ", "")]):
                    score += 1
        if score > best_score:
            best_score = score
            best_bank = bank_id
    return best_bank if best_score >= 2 else None


def parse_bank_statement(path: Path) -> list[dict[str, Any]]:
    """Parse a bank statement file (Excel/CSV) into standardized records."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = list(csv.reader(fh))
            if not reader:
                return []
            headers = reader[0]
            rows = reader[1:]
    elif suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd
            df = pd.read_excel(path, dtype=str).fillna("")
            headers = list(df.columns)
            rows = df.values.tolist()
        except Exception:
            return []
    else:
        return []

    bank_id = detect_bank_template(headers)
    template = BANK_TEMPLATES.get(bank_id) if bank_id else None

    records: list[dict[str, Any]] = []
    for row in rows:
        row_dict = {str(headers[i]): str(row[i]).strip() if i < len(row) else "" for i in range(len(headers))}
        record = _normalize_bank_row(row_dict, template)
        if record:
            records.append(record)
    return records


def _normalize_bank_row(row: dict[str, str], template: dict | None) -> dict[str, Any] | None:
    """Normalize a single bank statement row to standard format."""
    row_lower = {k.lower().replace(" ", ""): v for k, v in row.items()}

    # Extract date
    date_str = None
    date_cols = template["date_col"] if template else ["交易日期", "date", "日期"]
    for col in date_cols:
        val = row_lower.get(col.lower().replace(" ", ""), "") or row.get(col, "")
        if val:
            match = DATE_RE.search(str(val))
            if match:
                y, m, d = [int(x) for x in match.groups()]
                try:
                    date_str = date(y, m, d).isoformat()
                except ValueError:
                    pass
                break
    if not date_str:
        # Try any cell
        for v in row.values():
            match = DATE_RE.search(str(v))
            if match:
                y2, m2, d2 = [int(x) for x in match.groups()]
                try:
                    date_str = date(y2, m2, d2).isoformat()
                except ValueError:
                    pass
                break

    # Extract amounts
    amount_in_cols = template["amount_in"] if template else ["收入金额", "贷方金额"]
    amount_out_cols = template["amount_out"] if template else ["支出金额", "借方金额"]
    amount_in = _parse_bank_amount(row_lower, amount_in_cols, row)
    amount_out = _parse_bank_amount(row_lower, amount_out_cols, row)

    # Counterparty
    cp_cols = template["counterparty"] if template else ["对方户名", "对方名称"]
    counterparty = ""
    for col in cp_cols:
        counterparty = row_lower.get(col.lower().replace(" ", ""), "") or row.get(col, "")
        if counterparty:
            break

    # Summary
    sum_cols = template["summary"] if template else ["摘要", "用途", "备注"]
    summary = ""
    for col in sum_cols:
        summary = row_lower.get(col.lower().replace(" ", ""), "") or row.get(col, "")
        if summary:
            break

    # Balance
    bal_cols = template["balance"] if template else ["余额"]
    balance = _parse_bank_amount(row_lower, bal_cols, row)

    if not date_str and not amount_in and not amount_out:
        return None

    return {
        "date": date_str or "",
        "amount_in": round(amount_in, 2),
        "amount_out": round(amount_out, 2),
        "counterparty": counterparty,
        "summary": summary or "银行流水",
        "balance": round(balance, 2),
        "bank": template["name"] if template else "未知银行",
    }


def _parse_bank_amount(row_lower: dict, cols: list[str], original_row: dict) -> float:
    for col in cols:
        val = row_lower.get(col.lower().replace(" ", ""), "") or original_row.get(col, "")
        if val:
            cleaned = str(val).replace(",", "").replace("¥", "").replace("￥", "").strip()
            match = AMOUNT_RE.search(cleaned)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    pass
    return 0.0


def reconcile(
    bank_records: list[dict[str, Any]],
    ledger_records: list[LedgerRecord],
    tolerance: float = 0.01,
) -> dict[str, Any]:
    """Reconcile bank statements against ledger records.

    Returns matched pairs and unmatched items from both sides.
    """
    matched: list[dict] = []
    unmatched_bank: list[dict] = list(bank_records)
    unmatched_ledger: list[dict] = [r for r in ledger_records]

    for b_idx, bank_rec in enumerate(bank_records):
        best_idx = -1
        best_diff = float("inf")
        for l_idx, ledger_rec in enumerate(unmatched_ledger):
            # Match by date proximity and amount
            bank_amount = bank_rec.get("amount_out", 0) or -bank_rec.get("amount_in", 0)
            ledger_amount = (ledger_rec.debit or 0) - (ledger_rec.credit or 0)
            diff = abs(abs(bank_amount) - abs(ledger_amount))
            if diff <= tolerance and diff < best_diff:
                best_diff = diff
                best_idx = l_idx
        if best_idx >= 0:
            matched.append({
                "bank": bank_rec,
                "ledger": record_to_dict_simple(unmatched_ledger[best_idx]),
                "difference": round(best_diff, 2),
            })
            unmatched_ledger.pop(best_idx)
            if bank_rec in unmatched_bank:
                unmatched_bank.remove(bank_rec)

    return {
        "total_bank": len(bank_records),
        "total_ledger": len(ledger_records),
        "matched": len(matched),
        "unmatched_bank": len(unmatched_bank),
        "unmatched_ledger": len(unmatched_ledger),
        "matches": matched,
        "unmatched_bank_items": unmatched_bank,
        "unmatched_ledger_items": [record_to_dict_simple(r) for r in unmatched_ledger],
    }


def record_to_dict_simple(r: LedgerRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "date": r.record_date.isoformat() if r.record_date else "",
        "voucher_no": r.voucher_no,
        "account_name": r.account_name,
        "summary": r.summary,
        "debit": r.debit,
        "credit": r.credit,
        "balance": r.balance,
    }
