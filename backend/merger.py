"""Multi-table merge and budget comparison.

Inspired by Gandedong/audit-python- 'pandas三表合并' and '合并科目余额表'.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LedgerRecord, TaskJob

logger = logging.getLogger(__name__)


def merge_tables(
    db: Session,
    task_ids: list[int],
    merge_key: str = "account_code",
) -> dict[str, Any]:
    """Merge records from multiple tasks by a common key.

    Returns merged table as cross-tabulation.
    """
    all_records: dict[int, list[LedgerRecord]] = {}
    task_names: dict[int, str] = {}
    for task_id in task_ids:
        task = db.get(TaskJob, task_id)
        task_names[task_id] = f"#{task_id} {task.filename}" if task and task.file else f"任务#{task_id}"
        records = list(db.scalars(
            select(LedgerRecord).where(LedgerRecord.task_id == task_id).order_by(LedgerRecord.id)
        ))
        all_records[task_id] = records

    # Build merged dict keyed by merge_key
    merged: dict[str, dict[str, Any]] = {}
    for task_id, records in all_records.items():
        for r in records:
            key = str(getattr(r, merge_key, "") or "未分类")
            if key not in merged:
                merged[key] = {
                    "key": key,
                    "account_name": r.account_name or "",
                }
            merged[key][f"task_{task_id}_debit"] = (merged[key].get(f"task_{task_id}_debit", 0) or 0) + (r.debit or 0)
            merged[key][f"task_{task_id}_credit"] = (merged[key].get(f"task_{task_id}_credit", 0) or 0) + (r.credit or 0)
            merged[key][f"task_{task_id}_count"] = (merged[key].get(f"task_{task_id}_count", 0) or 0) + 1

    # Compute differences between first two tasks
    if len(task_ids) >= 2:
        t1, t2 = task_ids[0], task_ids[1]
        for key, val in merged.items():
            d1 = val.get(f"task_{t1}_debit", 0) or 0
            d2 = val.get(f"task_{t2}_debit", 0) or 0
            c1 = val.get(f"task_{t1}_credit", 0) or 0
            c2 = val.get(f"task_{t2}_credit", 0) or 0
            val["diff_debit"] = round(d1 - d2, 2)
            val["diff_credit"] = round(c1 - c2, 2)

    return {
        "tasks": [{"id": tid, "name": task_names.get(tid, "")} for tid in task_ids],
        "merge_key": merge_key,
        "rows": sorted(merged.values(), key=lambda x: str(x.get("key", ""))),
        "total_rows": len(merged),
    }


def budget_comparison(
    db: Session,
    budget_task_id: int,
    actual_task_id: int,
) -> dict[str, Any]:
    """Compare budget (预算) vs actual (实际) by account code.

    budget_task_id: task containing budget data
    actual_task_id: task containing actual data
    """
    budget_records = list(db.scalars(
        select(LedgerRecord).where(LedgerRecord.task_id == budget_task_id)
    ))
    actual_records = list(db.scalars(
        select(LedgerRecord).where(LedgerRecord.task_id == actual_task_id)
    ))

    # Aggregate by account_code
    budget_by_code: dict[str, dict] = {}
    for r in budget_records:
        code = r.account_code or "未分类"
        if code not in budget_by_code:
            budget_by_code[code] = {"code": code, "name": r.account_name or "", "budget_debit": 0, "budget_credit": 0}
        budget_by_code[code]["budget_debit"] += r.debit or 0
        budget_by_code[code]["budget_credit"] += r.credit or 0

    actual_by_code: dict[str, dict] = {}
    for r in actual_records:
        code = r.account_code or "未分类"
        if code not in actual_by_code:
            actual_by_code[code] = {"code": code, "name": r.account_name or "", "actual_debit": 0, "actual_credit": 0}
        actual_by_code[code]["actual_debit"] += r.debit or 0
        actual_by_code[code]["actual_credit"] += r.credit or 0

    # Merge budget and actual
    all_codes = set(budget_by_code.keys()) | set(actual_by_code.keys())
    comparison: list[dict] = []
    for code in sorted(all_codes):
        b = budget_by_code.get(code, {"code": code, "name": "", "budget_debit": 0, "budget_credit": 0})
        a = actual_by_code.get(code, {"code": code, "name": "", "actual_debit": 0, "actual_credit": 0})
        variance_debit = round(a["actual_debit"] - b["budget_debit"], 2)
        variance_credit = round(a["actual_credit"] - b["budget_credit"], 2)
        pct_debit = round(variance_debit / b["budget_debit"] * 100, 1) if b["budget_debit"] != 0 else None
        pct_credit = round(variance_credit / b["budget_credit"] * 100, 1) if b["budget_credit"] != 0 else None
        comparison.append({
            "account_code": code,
            "account_name": b["name"] or a["name"],
            "budget_debit": round(b["budget_debit"], 2),
            "budget_credit": round(b["budget_credit"], 2),
            "actual_debit": round(a["actual_debit"], 2),
            "actual_credit": round(a["actual_credit"], 2),
            "variance_debit": variance_debit,
            "variance_credit": variance_credit,
            "variance_pct_debit": pct_debit,
            "variance_pct_credit": pct_credit,
            "status": "over" if variance_debit > 0 else ("under" if variance_debit < 0 else "on_budget"),
        })

    total_budget_debit = sum(r["budget_debit"] for r in comparison)
    total_actual_debit = sum(r["actual_debit"] for r in comparison)
    total_budget_credit = sum(r["budget_credit"] for r in comparison)
    total_actual_credit = sum(r["actual_credit"] for r in comparison)

    return {
        "budget_task_id": budget_task_id,
        "actual_task_id": actual_task_id,
        "summary": {
            "total_budget_debit": round(total_budget_debit, 2),
            "total_actual_debit": round(total_actual_debit, 2),
            "total_budget_credit": round(total_budget_credit, 2),
            "total_actual_credit": round(total_actual_credit, 2),
            "overall_variance_debit": round(total_actual_debit - total_budget_debit, 2),
            "overall_variance_credit": round(total_actual_credit - total_budget_credit, 2),
        },
        "items": comparison,
        "over_budget_count": sum(1 for r in comparison if r["status"] == "over"),
        "under_budget_count": sum(1 for r in comparison if r["status"] == "under"),
        "on_budget_count": sum(1 for r in comparison if r["status"] == "on_budget"),
    }
