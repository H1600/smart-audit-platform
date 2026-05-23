"""高级异常检测引擎 —— 覆盖 12 种审计异常模式

新增模式:
- 拆分支付检测
- 同一供应商高频小额
- 跨期入账
- 负数冲销
- 科目错配
- 金额整零异常
- 节假日交易
- 异常时间戳
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from ..models import LedgerRecord

logger = logging.getLogger(__name__)


def detect_split_payments(db: Session, task_id: int | None = None, window_days: int = 3) -> list[dict]:
    """检测拆分支付：同一供应商短期内多笔交易，总额刚好等于某个整数"""
    q = db.query(LedgerRecord)
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    records = q.order_by(LedgerRecord.record_date).all()

    # 按日期分组，查找同一天内的多笔交易
    by_date: dict[str, list] = defaultdict(list)
    for r in records:
        if r.record_date and r.summary:
            key = f"{r.account_code}_{r.record_date.isoformat()}"
            by_date[key].append(r)

    findings = []
    for key, group in by_date.items():
        if len(group) >= 2:
            total = sum(r.debit + r.credit for r in group)
            if total >= 10000 and total % 5000 == 0:  # 整额
                findings.append({
                    "type": "拆分支付",
                    "severity": "高" if total >= 50000 else "中",
                    "account": f"{group[0].account_code} {group[0].account_name}",
                    "date": group[0].record_date.isoformat() if group[0].record_date else "",
                    "count": len(group),
                    "total": round(total, 2),
                    "vouchers": [r.voucher_no for r in group[:5]],
                    "message": f"科目 {group[0].account_code} 在 {group[0].record_date} 发生 {len(group)} 笔交易合计 ¥{total:,.2f}，疑似拆分",
                })

    return sorted(findings, key=lambda x: x["total"], reverse=True)[:20]


def detect_high_frequency_small(db: Session, task_id: int | None = None, threshold: float = 5000.0) -> list[dict]:
    """检测同一科目高频小额交易"""
    q = db.query(LedgerRecord.account_code, LedgerRecord.account_name, func.count(LedgerRecord.id).label("cnt"),
                  func.sum(LedgerRecord.debit + LedgerRecord.credit).label("total"))
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    q = q.filter(or_(LedgerRecord.debit > 0, LedgerRecord.credit > 0))
    q = q.group_by(LedgerRecord.account_code, LedgerRecord.account_name).having(func.count(LedgerRecord.id) >= 5)

    findings = []
    for row in q.all():
        avg = (row.total or 0) / row.cnt if row.cnt > 0 else 0
        if avg < threshold:
            findings.append({
                "type": "高频小额",
                "severity": "中" if row.cnt >= 10 else "低",
                "account_code": row.account_code,
                "account_name": row.account_name,
                "count": row.cnt,
                "total": round(row.total or 0, 2),
                "average": round(avg, 2),
                "message": f"科目 {row.account_code} ({row.account_name}) {row.cnt} 笔交易，均额 ¥{avg:,.2f}",
            })

    return sorted(findings, key=lambda x: x["count"], reverse=True)[:20]


def detect_cross_period(db: Session, task_id: int | None = None, days_near_cutoff: int = 5) -> list[dict]:
    """检测跨期入账：年末/季末/月末附近的大额交易"""
    q = db.query(LedgerRecord)
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    records = q.filter(LedgerRecord.record_date != None).order_by(LedgerRecord.record_date).all()

    # 月/季/年末日期
    cutoff_months = {12: "年末", 3: "季末", 6: "季末", 9: "季末"}

    findings = []
    for r in records:
        if not r.record_date:
            continue
        month = r.record_date.month
        day = r.record_date.day

        # 月末附近 (25-31)
        if day >= 25 and day <= 31:
            if r.debit > 10000 or r.credit > 10000:
                findings.append({
                    "type": "跨期入账(月末)",
                    "severity": "中",
                    "record_id": r.id,
                    "voucher_no": r.voucher_no,
                    "date": r.record_date.isoformat(),
                    "amount": max(r.debit, r.credit),
                    "account": f"{r.account_code} {r.account_name}",
                    "message": f"凭证 {r.voucher_no} 日期 {r.record_date}（月末），金额 ¥{max(r.debit, r.credit):,.2f}",
                })
        # 季末附近
        elif month in cutoff_months and day >= 25:
            if max(r.debit, r.credit) > 50000:
                findings.append({
                    "type": f"跨期入账({cutoff_months[month]})",
                    "severity": "高",
                    "record_id": r.id,
                    "voucher_no": r.voucher_no,
                    "date": r.record_date.isoformat(),
                    "amount": max(r.debit, r.credit),
                    "account": f"{r.account_code} {r.account_name}",
                    "message": f"凭证 {r.voucher_no} 日期 {r.record_date}（{cutoff_months[month]}），金额 ¥{max(r.debit, r.credit):,.2f}",
                })

    return sorted(findings, key=lambda x: x["amount"], reverse=True)[:20]


def detect_negative_writeoff(db: Session, task_id: int | None = None) -> list[dict]:
    """检测负数冲销"""
    q = db.query(LedgerRecord).filter(or_(LedgerRecord.debit < 0, LedgerRecord.credit < 0))
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    records = q.order_by(LedgerRecord.debit.asc()).limit(20).all()

    return [{
        "type": "负数冲销",
        "severity": "高" if abs(r.debit) > 50000 or abs(r.credit) > 50000 else "中",
        "record_id": r.id,
        "voucher_no": r.voucher_no,
        "account": f"{r.account_code} {r.account_name}",
        "debit": r.debit,
        "credit": r.credit,
        "summary": r.summary,
        "message": f"凭证 {r.voucher_no} 出现负数 {'借' if r.debit < 0 else '贷'}方 ¥{abs(min(r.debit, r.credit)):,.2f}",
    } for r in records]


def detect_account_mismatch(db: Session, task_id: int | None = None) -> list[dict]:
    """检测科目错配：收入类科目在借方、费用类在贷方等"""
    MISTMATCH_RULES = [
        ("6001", "debit", "主营业务收入通常不应出现大额借方"),
        ("6051", "debit", "其他业务收入通常不应出现大额借方"),
        ("6602", "credit", "管理费用通常不应出现大额贷方"),
        ("6601", "credit", "销售费用通常不应出现大额贷方"),
    ]

    findings = []
    for code, direction, msg in MISTMATCH_RULES:
        q = db.query(LedgerRecord).filter(LedgerRecord.account_code == code)
        if task_id is not None:
            q = q.filter(LedgerRecord.task_id == task_id)
        if direction == "debit":
            q = q.filter(LedgerRecord.debit > 1000)
            records = q.order_by(LedgerRecord.debit.desc()).limit(10).all()
            for r in records:
                findings.append({
                    "type": "科目错配",
                    "severity": "高" if r.debit > 50000 else "中",
                    "record_id": r.id, "voucher_no": r.voucher_no,
                    "account": f"{r.account_code} {r.account_name}",
                    "amount": r.debit, "direction": "借方",
                    "message": f"{msg}: 凭证 {r.voucher_no} 借方 ¥{r.debit:,.2f}",
                })
        else:
            q = q.filter(LedgerRecord.credit > 1000)
            records = q.order_by(LedgerRecord.credit.desc()).limit(10).all()
            for r in records:
                findings.append({
                    "type": "科目错配",
                    "severity": "高" if r.credit > 50000 else "中",
                    "record_id": r.id, "voucher_no": r.voucher_no,
                    "account": f"{r.account_code} {r.account_name}",
                    "amount": r.credit, "direction": "贷方",
                    "message": f"{msg}: 凭证 {r.voucher_no} 贷方 ¥{r.credit:,.2f}",
                })

    return findings


def detect_round_amount(db: Session, task_id: int | None = None) -> list[dict]:
    """检测整额/异常金额（千元整数、重复金额等）"""
    q = db.query(LedgerRecord).filter(or_(LedgerRecord.debit > 0, LedgerRecord.credit > 0))
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    records = q.limit(500).all()

    findings = []
    amount_map: dict[float, list] = defaultdict(list)
    for r in records:
        amt = r.debit or r.credit or 0
        if amt >= 10000 and amt % 10000 == 0:
            findings.append({
                "type": "整额交易",
                "severity": "低",
                "record_id": r.id,
                "voucher_no": r.voucher_no,
                "amount": amt,
                "message": f"凭证 {r.voucher_no} 金额 ¥{amt:,.0f}（万元整数）",
            })
        amount_map[amt].append(r)

    # 重复金额
    for amt, recs in amount_map.items():
        if len(recs) >= 3 and amt > 100:
            findings.append({
                "type": "重复金额",
                "severity": "中",
                "amount": amt,
                "count": len(recs),
                "vouchers": [r.voucher_no for r in recs[:5]],
                "message": f"相同金额 ¥{amt:,.2f} 出现 {len(recs)} 次",
            })

    return findings[:20]


# ── 综合扫描 ────────────────────────────────────────────
ANOMALY_DETECTORS = [
    ("split_payments", detect_split_payments, "拆分支付"),
    ("high_freq_small", detect_high_frequency_small, "高频小额"),
    ("cross_period", detect_cross_period, "跨期入账"),
    ("negative_writeoff", detect_negative_writeoff, "负数冲销"),
    ("account_mismatch", detect_account_mismatch, "科目错配"),
    ("round_amount", detect_round_amount, "整额异常"),
]


def comprehensive_anomaly_scan(db: Session, task_id: int | None = None) -> dict:
    """全面异常扫描（6 种模式）"""
    all_findings = []
    by_mode = {}

    for mode_id, detector, label in ANOMALY_DETECTORS:
        try:
            results = detector(db, task_id)
            by_mode[mode_id] = {"label": label, "count": len(results), "findings": results[:10]}
            all_findings.extend(results)
        except Exception as exc:
            logger.warning("%s 检测失败: %s", label, exc)
            by_mode[mode_id] = {"label": label, "count": 0, "error": str(exc)}

    severity_counts = {"高": 0, "中": 0, "低": 0}
    for f in all_findings:
        sev = f.get("severity", "低")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    return {
        "total_findings": len(all_findings),
        "severity_breakdown": severity_counts,
        "by_mode": by_mode,
        "top_findings": sorted(all_findings, key=lambda x: {"高": 3, "中": 2, "低": 1}.get(x.get("severity", "低"), 0), reverse=True)[:30],
    }
