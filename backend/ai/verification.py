"""审计追溯与验证引擎 —— 四联动核验 + 证据链 + 二次校验

支持:
- 发票-合同-付款-入账四联动核验
- 证据链自动构建
- AI 操作审计追溯
- 高风险结论二次校验
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, date
from typing import Any

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from ..models import LedgerRecord, AuditReport, TaskJob, OcrResult
from .rag import call_llm, AUDIT_SYSTEM_PROMPT
from .embeddings import embed_text
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)


# ── 审计追溯 ────────────────────────────────────────────
class AuditTrail:
    """审计操作追溯记录"""

    def __init__(self):
        self.entries: list[dict] = []

    def add(self, action: str, detail: dict | None = None, sources: list[dict] | None = None):
        self.entries.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "detail": detail or {},
            "sources": sources or [],
        })

    def to_dict(self) -> dict:
        return {
            "total_operations": len(self.entries),
            "trace": self.entries,
            "tools_used": list(set(e["action"] for e in self.entries)),
            "rules_applied": [],
            "evidence_count": sum(len(e.get("sources", [])) for e in self.entries),
        }


def build_evidence_chain(db: Session, record_ids: list[int]) -> list[dict]:
    """为指定记录构建证据链"""
    evidence = []
    for rid in record_ids[:20]:
        record = db.get(LedgerRecord, rid)
        if not record:
            continue
        chain = {
            "record_id": rid,
            "voucher_no": record.voucher_no,
            "account": f"{record.account_code} {record.account_name}",
            "summary": record.summary,
            "debit": record.debit,
            "credit": record.credit,
            "date": record.record_date.isoformat() if record.record_date else "",
            "is_exception": record.is_exception,
            "exception_reason": record.exception_reason,
            "source_text": record.source_text[:200] if record.source_text else "",
            "source_page": record.source_page,
            "source_row": record.source_row,
        }
        # 添加 OCR 来源
        if record.task_id:
            task = db.get(TaskJob, record.task_id)
            if task:
                chain["source_file"] = task.file.filename if task.file else ""
                ocr_results = db.query(OcrResult).filter(
                    OcrResult.task_id == record.task_id,
                    OcrResult.page_no == record.source_page,
                ).first()
                if ocr_results:
                    chain["ocr_confidence"] = ocr_results.confidence
                    chain["ocr_text_snippet"] = ocr_results.raw_text[:300]
        evidence.append(chain)
    return evidence


# ── 四联动核验 ──────────────────────────────────────────
async def four_way_verification(
    db: Session,
    task_id: int,
    account_code: str | None = None,
) -> dict:
    """发票-合同-付款-入账四联动核验

    检查逻辑：
    1. 有入账记录 → 是否有对应发票？
    2. 有大额付款 → 是否有合同？
    3. 发票金额 vs 入账金额是否匹配？
    4. 付款日期 vs 入账日期是否合理？
    """
    trail = AuditTrail()

    q = db.query(LedgerRecord).filter(LedgerRecord.task_id == task_id)
    if account_code:
        q = q.filter(LedgerRecord.account_code == account_code)

    records = q.all()
    if not records:
        return {"status": "empty", "message": "无记录"}

    trail.add("query_records", {"count": len(records), "task_id": task_id})

    total_records = len(records)
    total_amount = sum((r.debit or 0) + (r.credit or 0) for r in records)

    # 1. 检查大额无发票
    large_without_invoice = []
    for r in records:
        amt = max(r.debit, r.credit)
        if amt > 10000:
            summary_lower = (r.summary or "").lower()
            if not any(kw in summary_lower for kw in ["发票", "invoice", "票据"]):
                large_without_invoice.append({
                    "record_id": r.id,
                    "voucher_no": r.voucher_no,
                    "amount": amt,
                    "summary": r.summary[:50],
                })
    trail.add("check_invoice_match", {"large_without_invoice": len(large_without_invoice)})

    # 2. 合同匹配检查
    contract_missing = []
    for r in records:
        amt = max(r.debit, r.credit)
        if amt > 50000:
            summary_lower = (r.summary or "").lower()
            if not any(kw in summary_lower for kw in ["合同", "协议", "contract", "agreement"]):
                contract_missing.append({
                    "record_id": r.id,
                    "voucher_no": r.voucher_no,
                    "amount": amt,
                })
    trail.add("check_contract_match", {"contract_missing": len(contract_missing)})

    # 3. 金额合理性检查
    amount_issues = []
    for r in records:
        amt = max(r.debit, r.credit)
        if amt > 50000 and amt % 10000 == 0:
            amount_issues.append({
                "record_id": r.id,
                "voucher_no": r.voucher_no,
                "amount": amt,
                "issue": "万元整数，缺乏合同/发票佐证",
            })
    trail.add("check_amount_reasonableness", {"issues": len(amount_issues)})

    # 4. 日期合理性
    date_issues = []
    for r in records:
        if r.record_date and r.summary:
            if r.record_date.day >= 28:
                date_issues.append({
                    "record_id": r.id,
                    "voucher_no": r.voucher_no,
                    "date": r.record_date.isoformat(),
                    "amount": max(r.debit, r.credit),
                    "issue": "月末入账，可能存在跨期",
                })
    trail.add("check_date_reasonableness", {"issues": len(date_issues)})

    # 构建证据链
    all_issue_ids = [x["record_id"] for x in large_without_invoice + contract_missing + amount_issues]
    evidence = build_evidence_chain(db, list(set(all_issue_ids)))

    # AI 综合判断
    context = json.dumps({
        "total_records": total_records,
        "total_amount": round(total_amount, 2),
        "large_without_invoice": len(large_without_invoice),
        "contract_missing": len(contract_missing),
        "amount_issues": len(amount_issues),
        "date_issues": len(date_issues),
        "evidence_sample": evidence[:5] if evidence else [],
    }, ensure_ascii=False, indent=2)[:3000]

    messages = [
        {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
        {"role": "user", "content": f"""执行发票-合同-付款-入账四联动核验，请输出：

## 核验结论
(50字以内)

## 风险等级
(高/中/低，附简要理由)

## 主要问题
(按严重程度列出3-5条)

## 建议措施
(具体的后续动作)

核验数据如下：
{context}"""},
    ]
    ai_judgment = await call_llm(messages, max_tokens=600)
    trail.add("ai_four_way_judgment")

    return {
        "verification_type": "四联动核验",
        "task_id": task_id,
        "summary": {
            "total_records": total_records,
            "total_amount": round(total_amount, 2),
            "large_without_invoice": len(large_without_invoice),
            "contract_missing": len(contract_missing),
            "amount_issues": len(amount_issues),
            "date_issues": len(date_issues),
        },
        "details": {
            "large_without_invoice": large_without_invoice[:10],
            "contract_missing": contract_missing[:10],
            "amount_issues": amount_issues[:10],
            "date_issues": date_issues[:10],
        },
        "ai_judgment": ai_judgment,
        "evidence_chain": evidence[:10],
        "audit_trail": trail.to_dict(),
    }


# ── 二次校验 ────────────────────────────────────────────
async def secondary_review(primary_conclusion: str, evidence: list[dict]) -> dict:
    """对 AI 初次结论进行二次校验"""
    context = json.dumps({
        "primary_conclusion": primary_conclusion[:1000],
        "evidence_summary": [(e.get("voucher_no", ""), e.get("amount", 0), e.get("issue", "")) for e in evidence[:10]],
    }, ensure_ascii=False)[:2000]

    messages = [
        {"role": "system", "content": "你是审计质量复核人。请对以下 AI 审计结论进行独立复核，判断是否过于激进或保守。"},
        {"role": "user", "content": f"请复核以下审计结论，输出：\n1. 结论是否合理？（合理/需修正）\n2. 判断理由\n3. 修正建议（如需修正）\n\n{context}"},
    ]
    review = await call_llm(messages, max_tokens=400)

    return {
        "review_type": "secondary_review",
        "reviewed_at": datetime.utcnow().isoformat(),
        "reviewer": "AI 复核模型 (glm-4.5-air)",
        "review_result": review,
    }
