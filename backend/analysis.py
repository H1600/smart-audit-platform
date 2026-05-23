"""Data analysis & aggregation endpoints for visualization dashboard.

Inspired by Gandedong/audit-python- Matplotlib applications.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import LedgerRecord, TaskJob

logger = logging.getLogger(__name__)


def monthly_trend(db: Session, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
    """Monthly debit/credit trend for charts."""
    records = list(db.scalars(select(LedgerRecord).order_by(LedgerRecord.record_date)))
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})

    for r in records:
        if r.record_date is None:
            continue
        if start_date and r.record_date < start_date:
            continue
        if end_date and r.record_date > end_date:
            continue
        month_key = r.record_date.strftime("%Y-%m")
        monthly[month_key]["debit"] += r.debit or 0
        monthly[month_key]["credit"] += r.credit or 0

    months = sorted(monthly.keys())
    return [
        {"month": m, "debit": round(monthly[m]["debit"], 2), "credit": round(monthly[m]["credit"], 2)}
        for m in months
    ]


def account_distribution(db: Session) -> list[dict[str, Any]]:
    """Account-wise amount distribution for pie/bar charts."""
    stmt = (
        select(
            LedgerRecord.account_code,
            LedgerRecord.account_name,
            func.sum(LedgerRecord.debit).label("total_debit"),
            func.sum(LedgerRecord.credit).label("total_credit"),
            func.count(LedgerRecord.id).label("cnt"),
        )
        .group_by(LedgerRecord.account_code, LedgerRecord.account_name)
        .order_by(func.sum(LedgerRecord.debit).desc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "account_code": row.account_code or "未映射",
            "account_name": row.account_name or "未映射",
            "total_debit": round(float(row.total_debit or 0), 2),
            "total_credit": round(float(row.total_credit or 0), 2),
            "count": int(row.cnt or 0),
        }
        for row in rows[:30]
    ]


def exception_distribution(db: Session) -> dict[str, Any]:
    """Exception breakdown by type."""
    stmt = select(LedgerRecord).where(LedgerRecord.is_exception == True)
    records = list(db.scalars(stmt))
    reason_counts: dict[str, int] = defaultdict(int)
    total_debit = 0.0
    total_credit = 0.0

    for r in records:
        total_debit += r.debit or 0
        total_credit += r.credit or 0
        if r.exception_reason:
            for reason in r.exception_reason.split("；"):
                reason = reason.strip()
                if reason:
                    reason_counts[reason] += 1
        else:
            reason_counts["未知异常"] += 1

    return {
        "total_exceptions": len(records),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "breakdown": [
            {"reason": k, "count": v} for k, v in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
        ],
    }


def amount_distribution(db: Session) -> list[dict[str, Any]]:
    """Amount range distribution for histogram."""
    records = list(db.scalars(select(LedgerRecord)))
    buckets = [
        ("0-100", 0, 100),
        ("100-500", 100, 500),
        ("500-1000", 500, 1000),
        ("1000-5000", 1000, 5000),
        ("5000-10000", 5000, 10000),
        ("10000-50000", 10000, 50000),
        ("50000-100000", 50000, 100000),
        ("100000+", 100000, float("inf")),
    ]
    result: list[dict[str, Any]] = []
    for label, lo, hi in buckets:
        cnt = sum(1 for r in records if lo <= max(r.debit or 0, r.credit or 0, abs(r.balance or 0)) < hi)
        result.append({"range": label, "count": cnt})
    return result


def task_statistics(db: Session) -> dict[str, Any]:
    """Aggregate task statistics."""
    total = db.scalar(select(func.count(TaskJob.id))) or 0
    completed = db.scalar(select(func.count(TaskJob.id)).where(TaskJob.status == "completed")) or 0
    failed = db.scalar(select(func.count(TaskJob.id)).where(TaskJob.status == "failed")) or 0
    running = db.scalar(select(func.count(TaskJob.id)).where(TaskJob.status.in_(["pending", "running", "queued"]))) or 0
    return {
        "total_tasks": total,
        "completed": completed,
        "failed": failed,
        "running": running,
    }


def full_analysis(db: Session) -> dict[str, Any]:
    """Return all analysis data for the dashboard."""
    return {
        "monthly_trend": monthly_trend(db),
        "account_distribution": account_distribution(db),
        "exception_distribution": exception_distribution(db),
        "amount_distribution": amount_distribution(db),
        "task_statistics": task_statistics(db),
    }
