"""Audit sampling module — random, stratified, and large-amount sampling.

Inspired by Gandedong/audit-python- '随机抽取凭证'.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import LedgerRecord

logger = logging.getLogger(__name__)


def random_sample(db: Session, task_id: int | None, sample_size: int, **filters: Any) -> list[dict[str, Any]]:
    """Randomly select N records from filtered results."""
    stmt = _build_filter_stmt(task_id, **filters)
    records = list(db.scalars(stmt))
    if not records:
        return []
    actual_size = min(sample_size, len(records))
    chosen = random.sample(records, actual_size)
    return [_record_to_sampling_dict(r, "random") for r in chosen]


def stratified_sample(
    db: Session,
    task_id: int | None,
    sample_size: int,
    stratify_by: str = "account_code",
    **filters: Any,
) -> list[dict[str, Any]]:
    """Stratified sampling: proportional allocation by stratum."""
    stmt = _build_filter_stmt(task_id, **filters)
    all_records = list(db.scalars(stmt))
    if not all_records:
        return []

    # Group by stratum
    strata: dict[str, list[LedgerRecord]] = {}
    for r in all_records:
        key = str(getattr(r, stratify_by, "") or "未分类")
        strata.setdefault(key, []).append(r)

    total = len(all_records)
    chosen: list[LedgerRecord] = []
    for key, group in strata.items():
        stratum_n = max(1, round(sample_size * len(group) / total))
        stratum_n = min(stratum_n, len(group))
        chosen.extend(random.sample(group, stratum_n))

    # Trim if oversampled due to rounding
    if len(chosen) > sample_size:
        chosen = random.sample(chosen, sample_size)

    return [_record_to_sampling_dict(r, f"stratified:{stratify_by}") for r in chosen]


def large_amount_sample(
    db: Session,
    task_id: int | None,
    threshold: float = 10000.0,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Select all records where max(debit, credit) >= threshold."""
    stmt = _build_filter_stmt(task_id, **filters)
    all_records = list(db.scalars(stmt))
    chosen = [r for r in all_records if max(r.debit or 0, r.credit or 0, abs(r.balance or 0)) >= threshold]
    return [_record_to_sampling_dict(r, f"large_amount:>={threshold}") for r in chosen]


def _build_filter_stmt(task_id: int | None, **filters: Any):
    stmt = select(LedgerRecord)
    if task_id is not None:
        stmt = stmt.where(LedgerRecord.task_id == task_id)
    if filters.get("start_date"):
        stmt = stmt.where(LedgerRecord.record_date >= filters["start_date"])
    if filters.get("end_date"):
        stmt = stmt.where(LedgerRecord.record_date <= filters["end_date"])
    if filters.get("account"):
        like = f"%{filters['account']}%"
        stmt = stmt.where((LedgerRecord.account_code.like(like)) | (LedgerRecord.account_name.like(like)))
    if filters.get("account_code"):
        stmt = stmt.where(LedgerRecord.account_code == filters["account_code"])
    if filters.get("is_exception") is not None:
        stmt = stmt.where(LedgerRecord.is_exception == bool(filters["is_exception"]))
    stmt = stmt.order_by(LedgerRecord.id)
    return stmt


def _record_to_sampling_dict(r: LedgerRecord, method: str) -> dict[str, Any]:
    return {
        "id": r.id,
        "task_id": r.task_id,
        "date": r.record_date.isoformat() if r.record_date else "",
        "voucher_no": r.voucher_no,
        "account_code": r.account_code,
        "account_name": r.account_name,
        "summary": r.summary,
        "debit": r.debit,
        "credit": r.credit,
        "balance": r.balance,
        "is_exception": r.is_exception,
        "exception_reason": r.exception_reason,
        "sampling_method": method,
    }


def export_sampling_result(records: list[dict[str, Any]], fmt: str = "excel") -> str:
    """Export sampling result to a file, return file path."""
    import csv
    import os
    from datetime import datetime
    from pathlib import Path

    from .settings import EXPORT_DIR

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    headers = ["采样方法", "记录ID", "日期", "凭证号", "科目编码", "科目名称", "摘要", "借方", "贷方", "余额", "异常"]

    if fmt == "csv":
        path = EXPORT_DIR / f"sampling_{timestamp}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            for r in records:
                writer.writerow([
                    r.get("sampling_method", ""), r["id"], r.get("date", ""), r.get("voucher_no", ""),
                    r.get("account_code", ""), r.get("account_name", ""), r.get("summary", ""),
                    r.get("debit", 0), r.get("credit", 0), r.get("balance", 0),
                    "是" if r.get("is_exception") else "否",
                ])
        return str(path)

    # Excel
    try:
        from openpyxl import Workbook

        path = EXPORT_DIR / f"sampling_{timestamp}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "审计抽样结果"
        ws.append(headers)
        for r in records:
            ws.append([
                r.get("sampling_method", ""), r["id"], r.get("date", ""), r.get("voucher_no", ""),
                r.get("account_code", ""), r.get("account_name", ""), r.get("summary", ""),
                r.get("debit", 0), r.get("credit", 0), r.get("balance", 0),
                "是" if r.get("is_exception") else "否",
            ])
        wb.save(path)
        return str(path)
    except Exception:
        # fallback to csv
        return export_sampling_result(records, fmt="csv")
