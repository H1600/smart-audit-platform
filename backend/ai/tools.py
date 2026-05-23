"""AI 可调用工具集 —— 让模型从"问答"升级为"执行"

提供后端工具函数，AI 可通过 function calling 调用：
- 查账、对账、归因
- 报告生成
- 底稿生成
- 索引重建
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, and_, or_
from sqlalchemy.orm import Session

from ..models import AuditReport, FileUpload, LedgerRecord, OcrResult, TaskJob
from .embeddings import embed_text
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)

# ── 工具定义（给 LLM 的 function calling schema）────────
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_ledger_records",
            "description": "查询账务记录。可按科目编码、凭证号、日期范围、金额范围等过滤",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_code": {"type": "string", "description": "科目编码，如 1122"},
                    "account_name": {"type": "string", "description": "科目名称关键词"},
                    "voucher_no": {"type": "string", "description": "凭证号"},
                    "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    "min_amount": {"type": "number", "description": "最小金额"},
                    "max_amount": {"type": "number", "description": "最大金额"},
                    "is_exception": {"type": "boolean", "description": "是否仅异常记录"},
                    "limit": {"type": "integer", "default": 50, "description": "返回条数上限"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_summary",
            "description": "获取指定科目的汇总统计（借方合计、贷方合计、记录数、异常数）",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_code": {"type": "string", "description": "科目编码，如 1122"},
                    "task_id": {"type": "integer", "description": "可选：限定任务"},
                },
                "required": ["account_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconcile_account",
            "description": "对指定科目执行借贷平衡校验，返回差额和异常明细",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_code": {"type": "string", "description": "科目编码"},
                    "task_id": {"type": "integer", "description": "可选：限定任务"},
                    "tolerance": {"type": "number", "default": 0.01, "description": "容差（元）"},
                },
                "required": ["account_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_anomalies",
            "description": "检测异常记录：大额交易、重复凭证、异常科目、凭证缺失",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "可选：限定任务"},
                    "large_threshold": {"type": "number", "default": 50000, "description": "大额阈值（元）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_similar_records",
            "description": "语义检索：查找与给定描述相似的账务记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询描述"},
                    "top_k": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_audit_workpaper",
            "description": "生成指定任务的审计底稿摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "任务 ID"},
                    "format": {"type": "string", "enum": ["summary", "detail", "risk"], "default": "summary"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_list",
            "description": "获取已处理完成的任务列表",
            "parameters": {"type": "object", "properties": {},},
        },
    },
]


# ── 工具实现 ────────────────────────────────────────────

def _fmt_date(d: Any) -> str:
    if d is None:
        return ""
    if isinstance(d, (date, datetime)):
        return d.isoformat()[:10]
    return str(d)[:10]


def tool_query_ledger_records(db: Session, **kwargs: Any) -> dict[str, Any]:
    """查询账务记录"""
    q = db.query(LedgerRecord)
    if kwargs.get("account_code"):
        q = q.filter(LedgerRecord.account_code == kwargs["account_code"])
    if kwargs.get("account_name"):
        q = q.filter(LedgerRecord.account_name.contains(kwargs["account_name"]))
    if kwargs.get("voucher_no"):
        q = q.filter(LedgerRecord.voucher_no == kwargs["voucher_no"])
    if kwargs.get("start_date"):
        q = q.filter(LedgerRecord.record_date >= kwargs["start_date"])
    if kwargs.get("end_date"):
        q = q.filter(LedgerRecord.record_date <= kwargs["end_date"])
    if kwargs.get("min_amount") is not None:
        q = q.filter(or_(LedgerRecord.debit >= kwargs["min_amount"], LedgerRecord.credit >= kwargs["min_amount"]))
    if kwargs.get("max_amount") is not None:
        q = q.filter(and_(LedgerRecord.debit <= kwargs["max_amount"], LedgerRecord.credit <= kwargs["max_amount"]))
    if kwargs.get("is_exception") is not None:
        q = q.filter(LedgerRecord.is_exception == kwargs["is_exception"])

    limit = min(kwargs.get("limit", 50), 200)
    records = q.order_by(LedgerRecord.record_date.desc()).limit(limit).all()

    total_debit = sum(r.debit or 0 for r in records)
    total_credit = sum(r.credit or 0 for r in records)

    items = [
        {
            "id": r.id,
            "voucher_no": r.voucher_no,
            "account_code": r.account_code,
            "account_name": r.account_name,
            "summary": r.summary,
            "debit": r.debit,
            "credit": r.credit,
            "date": _fmt_date(r.record_date),
            "is_exception": r.is_exception,
            "exception_reason": r.exception_reason,
        }
        for r in records
    ]

    return {"count": len(items), "total_debit": round(total_debit, 2), "total_credit": round(total_credit, 2), "records": items}


def tool_get_account_summary(db: Session, account_code: str, task_id: int | None = None) -> dict[str, Any]:
    """科目汇总统计"""
    q = db.query(LedgerRecord).filter(LedgerRecord.account_code == account_code)
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)

    records = q.all()
    if not records:
        return {"account_code": account_code, "record_count": 0, "message": "无记录"}

    total_debit = sum(r.debit or 0 for r in records)
    total_credit = sum(r.credit or 0 for r in records)
    exception_count = sum(1 for r in records if r.is_exception)

    # 按月份汇总
    monthly: dict[str, dict] = {}
    for r in records:
        m = _fmt_date(r.record_date)[:7] if r.record_date else "未知"
        if m not in monthly:
            monthly[m] = {"debit": 0.0, "credit": 0.0, "count": 0}
        monthly[m]["debit"] += r.debit or 0
        monthly[m]["credit"] += r.credit or 0
        monthly[m]["count"] += 1

    return {
        "account_code": account_code,
        "account_name": records[0].account_name if records else "",
        "record_count": len(records),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "balance": round(total_debit - total_credit, 2),
        "exception_count": exception_count,
        "monthly_trend": [{"month": k, **v} for k, v in sorted(monthly.items())],
    }


def tool_reconcile_account(db: Session, account_code: str, task_id: int | None = None, tolerance: float = 0.01) -> dict[str, Any]:
    """科目借贷平衡校验"""
    q = db.query(LedgerRecord).filter(LedgerRecord.account_code == account_code)
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)

    records = q.all()
    total_debit = sum(r.debit or 0 for r in records)
    total_credit = sum(r.credit or 0 for r in records)
    diff = abs(total_debit - total_credit)
    balanced = diff <= tolerance

    # 凭证级核对
    voucher_imbalances = []
    by_voucher: dict[str, dict] = {}
    for r in records:
        vno = r.voucher_no or "空凭证"
        if vno not in by_voucher:
            by_voucher[vno] = {"debit": 0.0, "credit": 0.0, "records": []}
        by_voucher[vno]["debit"] += r.debit or 0
        by_voucher[vno]["credit"] += r.credit or 0
        by_voucher[vno]["records"].append({"id": r.id, "summary": r.summary, "debit": r.debit, "credit": r.credit})

    for vno, data in by_voucher.items():
        vdiff = abs(data["debit"] - data["credit"])
        if vdiff > tolerance:
            voucher_imbalances.append({"voucher_no": vno, "debit": round(data["debit"], 2), "credit": round(data["credit"], 2), "diff": round(vdiff, 2)})

    return {
        "account_code": account_code,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "diff": round(diff, 2),
        "balanced": balanced,
        "tolerance": tolerance,
        "voucher_count": len(by_voucher),
        "imbalanced_vouchers": voucher_imbalances[:20],
    }


def tool_detect_anomalies(db: Session, task_id: int | None = None, large_threshold: float = 50000.0) -> dict[str, Any]:
    """综合异常检测"""
    findings = []

    # 大额交易
    q = db.query(LedgerRecord).filter(or_(LedgerRecord.debit > large_threshold, LedgerRecord.credit > large_threshold))
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    for r in q.order_by(LedgerRecord.debit.desc()).limit(20).all():
        findings.append({"type": "大额交易", "severity": "高" if max(r.debit, r.credit) > 100000 else "中", "record_id": r.id, "voucher_no": r.voucher_no, "account": f"{r.account_code} {r.account_name}", "amount": max(r.debit, r.credit), "summary": r.summary})

    # 重复凭证
    dup_q = db.query(LedgerRecord.voucher_no, func.count(LedgerRecord.id).label("cnt")).filter(LedgerRecord.voucher_no != "").group_by(LedgerRecord.voucher_no).having(func.count(LedgerRecord.id) > 1)
    if task_id is not None:
        dup_q = dup_q.filter(LedgerRecord.task_id == task_id)
    for vno, cnt in dup_q.limit(10).all():
        findings.append({"type": "重复凭证", "severity": "中", "voucher_no": vno, "count": cnt, "message": f"凭证 {vno} 出现 {cnt} 次"})

    # 负数/零金额
    q = db.query(LedgerRecord).filter(and_(LedgerRecord.debit == 0, LedgerRecord.credit == 0))
    if task_id is not None:
        q = q.filter(LedgerRecord.task_id == task_id)
    zero_count = q.count()
    if zero_count > 0:
        findings.append({"type": "零金额凭证", "severity": "低", "count": zero_count, "message": f"有 {zero_count} 条凭证借贷方均为0"})

    return {"total_findings": len(findings), "findings": findings, "threshold": large_threshold}


def tool_search_similar(db: Session, query: str, top_k: int = 10) -> dict[str, Any]:
    """语义相似检索"""
    store = get_vector_store()
    if store.count == 0:
        return {"results": [], "message": "索引为空，请先触发数据索引"}

    query_vec = embed_text(query)
    results = store.search(query_vec, top_k=top_k)
    return {
        "query": query,
        "results": [
            {"id": r["id"], "text": r["text"][:200], "score": round(r["score"], 4), "metadata": r.get("metadata", {})}
            for r in results
        ],
        "total": len(results),
    }


def tool_generate_workpaper(db: Session, task_id: int, format: str = "summary") -> dict[str, Any]:
    """生成审计底稿摘要"""
    task = db.get(TaskJob, task_id)
    if not task:
        return {"error": "任务不存在"}

    records = db.query(LedgerRecord).filter(LedgerRecord.task_id == task_id).all()
    exceptions = [r for r in records if r.is_exception]
    reports = db.query(AuditReport).filter(AuditReport.task_id == task_id).all()

    total_debit = sum(r.debit or 0 for r in records)
    total_credit = sum(r.credit or 0 for r in records)

    paper = {
        "task_id": task_id,
        "filename": task.file.filename if task.file else "未知",
        "status": task.status,
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {"total_records": len(records), "exception_count": len(exceptions), "total_debit": round(total_debit, 2), "total_credit": round(total_credit, 2), "balance": round(total_debit - total_credit, 2), "report_count": len(reports),},
    }

    if format in ("detail", "risk"):
        # 科目汇总
        by_account: dict[str, dict] = {}
        for r in records:
            code = r.account_code or "未映射"
            if code not in by_account:
                by_account[code] = {"name": r.account_name or "未映射", "debit": 0.0, "credit": 0.0, "count": 0, "exception": 0}
            by_account[code]["debit"] += r.debit or 0
            by_account[code]["credit"] += r.credit or 0
            by_account[code]["count"] += 1
            if r.is_exception:
                by_account[code]["exception"] += 1
        paper["account_breakdown"] = [
            {"code": k, "name": v["name"], "debit": round(v["debit"], 2), "credit": round(v["credit"], 2), "count": v["count"], "exceptions": v["exception"]}
            for k, v in sorted(by_account.items(), key=lambda x: x[1]["debit"] + x[1]["credit"], reverse=True)
        ]

    if format == "risk":
        paper["top_exceptions"] = [
            {"id": r.id, "voucher": r.voucher_no, "account": f"{r.account_code} {r.account_name}", "summary": r.summary, "reason": r.exception_reason, "debit": r.debit, "credit": r.credit}
            for r in sorted(exceptions, key=lambda x: (x.debit or 0) + (x.credit or 0), reverse=True)[:20]
        ]
        paper["reports"] = [{"rule": r.rule_name, "passed": r.passed, "details": r.details[:200]} for r in reports]

    return paper


def tool_get_task_list(db: Session) -> dict[str, Any]:
    """获取已完成任务列表"""
    tasks = db.query(TaskJob).order_by(TaskJob.id.desc()).limit(20).all()
    return {
        "tasks": [
            {
                "id": t.id,
                "filename": t.file.filename if t.file else "",
                "status": t.status,
                "progress": t.progress,
                "step": t.current_step,
            }
            for t in tasks
        ]
    }


# ── 工具调度 ────────────────────────────────────────────
TOOL_MAP = {
    "query_ledger_records": tool_query_ledger_records,
    "get_account_summary": tool_get_account_summary,
    "reconcile_account": tool_reconcile_account,
    "detect_anomalies": tool_detect_anomalies,
    "search_similar_records": tool_search_similar,
    "generate_audit_workpaper": tool_generate_workpaper,
    "get_task_list": tool_get_task_list,
}


def execute_tool(name: str, arguments: dict[str, Any], db: Session) -> dict[str, Any]:
    """执行工具调用"""
    func = TOOL_MAP.get(name)
    if not func:
        return {"error": f"未知工具: {name}"}
    try:
        return func(db, **arguments)
    except Exception as exc:
        logger.error("工具 %s 执行失败: %s", name, exc)
        return {"error": f"工具执行失败: {exc}"}
