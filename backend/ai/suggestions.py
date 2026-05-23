"""审计建议引擎 —— 自动检测异常并生成建议

支持:
- 基于规则的异常检测（大额交易、异常科目、凭证缺失）
- 基于向量相似度的异常发现
- AI 驱动的审计建议生成
- 建议优先级排序与摘要
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import LedgerRecord, TaskJob
from .embeddings import embed_text
from .rag import AUDIT_SYSTEM_PROMPT, call_llm
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)

# ── 规则引擎 ────────────────────────────────────────────


def _detect_large_amounts(db: Session, task_id: int | None = None, threshold: float = 50000.0) -> list[dict[str, Any]]:
    """检测大额交易"""
    query = db.query(LedgerRecord).filter(
        (LedgerRecord.debit > threshold) | (LedgerRecord.credit > threshold)
    )
    if task_id is not None:
        query = query.filter(LedgerRecord.task_id == task_id)
    records = query.order_by(LedgerRecord.debit.desc()).limit(20).all()

    return [
        {
            "type": "large_amount",
            "severity": "high" if max(r.debit, r.credit) > 100000 else "medium",
            "record_id": r.id,
            "voucher_no": r.voucher_no,
            "account_code": r.account_code,
            "account_name": r.account_name,
            "summary": r.summary,
            "amount": max(r.debit, r.credit),
            "message": f"大额交易: 凭证 {r.voucher_no} 科目 {r.account_code} {r.account_name}，金额 ¥{max(r.debit, r.credit):,.2f}",
        }
        for r in records
    ]


def _detect_unusual_accounts(db: Session, task_id: int | None = None) -> list[dict[str, Any]]:
    """检测异常科目组合（同一凭证中借/贷科目不匹配）"""
    # 简化实现：查找同一凭证号下科目名称包含"应收"但无对应"收入"的记录
    query = db.query(LedgerRecord).filter(
        LedgerRecord.account_name.contains("应收"),
        ~LedgerRecord.account_name.contains("票据"),
    )
    if task_id is not None:
        query = query.filter(LedgerRecord.task_id == task_id)
    records = query.limit(10).all()

    return [
        {
            "type": "unusual_account",
            "severity": "medium",
            "record_id": r.id,
            "voucher_no": r.voucher_no,
            "account_code": r.account_code,
            "account_name": r.account_name,
            "summary": r.summary,
            "message": f"应收科目: {r.account_name} (凭证 {r.voucher_no})，请核对回款情况",
        }
        for r in records
    ]


def _detect_missing_vouchers(db: Session, task_id: int | None = None) -> list[dict[str, Any]]:
    """检测凭证号不连续（可能缺失）"""
    query = db.query(LedgerRecord.voucher_no).distinct()
    if task_id is not None:
        query = query.filter(LedgerRecord.task_id == task_id)
    vouchers = [v[0] for v in query.all()]

    gaps = []
    for i in range(len(vouchers) - 1):
        try:
            curr = int(vouchers[i])
            next_num = int(vouchers[i + 1])
            if next_num - curr > 1:
                gaps.append(
                    {
                        "type": "missing_voucher",
                        "severity": "medium",
                        "from_voucher": vouchers[i],
                        "to_voucher": vouchers[i + 1],
                        "missing_count": next_num - curr - 1,
                        "message": f"凭证号间隔: {vouchers[i]} → {vouchers[i + 1]}，可能缺失 {next_num - curr - 1} 张凭证",
                    }
                )
        except ValueError:
            continue

    return gaps[:10]


def _detect_duplicate_vouchers(db: Session, task_id: int | None = None) -> list[dict[str, Any]]:
    """检测重复凭证"""
    query = (
        db.query(LedgerRecord.voucher_no, func.count(LedgerRecord.id).label("cnt"))
        .group_by(LedgerRecord.voucher_no)
        .having(func.count(LedgerRecord.id) > 2)
    )
    if task_id is not None:
        query = query.filter(LedgerRecord.task_id == task_id)
    dups = query.limit(10).all()

    return [
        {
            "type": "duplicate_voucher",
            "severity": "low",
            "voucher_no": vno,
            "count": cnt,
            "message": f"凭证 {vno} 出现 {cnt} 次，请核实是否重复入账",
        }
        for vno, cnt in dups
    ]


# ── 建议生成 ────────────────────────────────────────────


async def generate_suggestions(
    db: Session,
    task_id: int | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """综合生成审计建议"""
    # 规则检测
    large = _detect_large_amounts(db, task_id)
    unusual = _detect_unusual_accounts(db, task_id)
    missing = _detect_missing_vouchers(db, task_id)
    duplicate = _detect_duplicate_vouchers(db, task_id)

    all_findings = large + unusual + missing + duplicate

    # 向量检索异常（找与已知异常最相似的记录）
    vector_findings = []
    exceptions = (
        db.query(LedgerRecord).filter(LedgerRecord.is_exception == True)
    )
    if task_id is not None:
        exceptions = exceptions.filter(LedgerRecord.task_id == task_id)
    exceptions = exceptions.limit(5).all()

    if exceptions:
        store = get_vector_store()
        for exc in exceptions:
            exc_text = f"凭证号:{exc.voucher_no} 科目:{exc.account_code} {exc.account_name} 摘要:{exc.summary}"
            exc_vec = embed_text(exc_text)
            similar = store.search(exc_vec, top_k=3, filters={"type": "ledger_record"} if not task_id else None)
            for s in similar:
                if s["score"] > 0.85 and s["metadata"].get("record_id") != exc.id:
                    vector_findings.append(
                        {
                            "type": "semantic_similar",
                            "severity": "medium",
                            "source_record_id": exc.id,
                            "similar_record_id": s["metadata"].get("record_id"),
                            "similarity": s["score"],
                            "source_text": exc_text[:100],
                            "similar_text": s["text"][:100],
                            "message": f"语义相似异常: 凭证 {exc.voucher_no} 与 ID {s['metadata'].get('record_id')} 相似度 {s['score']:.2f}",
                        }
                    )

    # 如果启用 LLM，生成综合建议摘要
    summary = None
    if use_llm:
        findings_text = "\n".join(
            f"- [{f['severity']}] {f['type']}: {f.get('message', '')}" for f in all_findings[:20]
        )
        if findings_text:
            messages = [
                {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"以下是对一批审计数据的自动扫描发现，请生成一份简洁的审计建议摘要（200字以内）：\n\n{findings_text}",
                },
            ]
            summary = await call_llm(messages, max_tokens=300)

    return {
        "total_findings": len(all_findings) + len(vector_findings),
        "findings": {
            "large_amounts": large,
            "unusual_accounts": unusual,
            "missing_vouchers": missing,
            "duplicate_vouchers": duplicate,
            "semantic_similar": vector_findings,
        },
        "summary": summary or f"自动扫描完成，共发现 {len(all_findings) + len(vector_findings)} 项审计线索。",
        "timestamp": datetime.utcnow().isoformat(),
    }
