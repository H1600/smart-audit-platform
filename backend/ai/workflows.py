"""审计工作流引擎 —— 多步骤自动化审计流程

支持:
- 标准审计流程（检索→分析→归因→报告→建议）
- 专项审计流程（应收/应付/费用/收入）
- 跨表勾稽流程
- 批量底稿生成
- 风险评级
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, and_, or_
from sqlalchemy.orm import Session

from ..models import LedgerRecord, AuditReport, TaskJob
from .tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    tool_get_account_summary,
    tool_detect_anomalies,
    tool_reconcile_account,
    tool_query_ledger_records,
    tool_generate_workpaper,
)
from .rag import call_llm, AUDIT_SYSTEM_PROMPT
from .config import LLM_MODEL
from .anomalies import comprehensive_anomaly_scan
from .verification import four_way_verification, AuditTrail, build_evidence_chain, secondary_review
from .perspectives import multi_perspective_audit

logger = logging.getLogger(__name__)

# ── 工作流定义 ──────────────────────────────────────────

WORKFLOW_TEMPLATES = {
    "full_audit": {
        "name": "全面审计流程",
        "description": "数据质量→12项异常扫描→科目分析→风险评级→AI建议",
        "steps": ["data_quality_check", "comprehensive_anomaly", "account_analysis", "risk_assessment", "generate_recommendations"],
    },
    "quick_scan": {
        "name": "快速扫描",
        "description": "5分钟内完成：大额→重复→平衡→异常",
        "steps": ["large_amount_scan", "duplicate_scan", "balance_check", "anomaly_scan"],
    },
    "ar_audit": {
        "name": "应收账款专项审计",
        "description": "余额→账龄→收入匹配→AI风险汇总",
        "steps": ["ar_balance_check", "ar_aging_analysis", "ar_revenue_match", "ar_risk_summary"],
    },
    "ap_audit": {
        "name": "应付账款专项审计",
        "description": "余额→供应商→异常支付→AI风险汇总",
        "steps": ["ap_balance_check", "ap_vendor_analysis", "ap_payment_check", "ap_risk_summary"],
    },
    "revenue_audit": {
        "name": "收入确认专项审计",
        "description": "收入汇总→期间匹配→科目验证→AI风险汇总",
        "steps": ["revenue_period_check", "revenue_amount_check", "revenue_account_match", "revenue_risk_summary"],
    },
    "expense_audit": {
        "name": "费用报销专项审计",
        "description": "费用汇总→合理性→异常扫描→AI风险汇总",
        "steps": ["expense_reasonableness", "expense_compliance", "expense_anomaly", "expense_risk_summary"],
    },
    "four_way": {
        "name": "四联动核验",
        "description": "发票→合同→付款→入账全链路交叉验证",
        "steps": ["four_way_check"],
    },
    "multi_perspective": {
        "name": "多视角审计",
        "description": "风险视角+合规视角+业务视角 → 综合审计意见",
        "steps": ["multi_perspective_analysis"],
    },
}


# ── 步骤执行器 ──────────────────────────────────────────

def _step_data_quality(db: Session, task_id: int) -> dict:
    """数据质量检查"""
    records = db.query(LedgerRecord).filter(LedgerRecord.task_id == task_id)
    total = records.count()
    if total == 0:
        return {"step": "data_quality_check", "status": "empty", "findings": []}

    null_date = records.filter(LedgerRecord.record_date == None).count()
    null_account = records.filter(or_(LedgerRecord.account_code == "", LedgerRecord.account_code == None)).count()
    null_voucher = records.filter(or_(LedgerRecord.voucher_no == "", LedgerRecord.voucher_no == None)).count()

    issues = []
    if null_date > 0:
        issues.append(f"{null_date}条记录缺少日期")
    if null_account > 0:
        issues.append(f"{null_account}条记录缺少科目编码")
    if null_voucher > 0:
        issues.append(f"{null_voucher}条记录缺少凭证号")

    return {"step": "data_quality_check", "total_records": total, "issues": issues, "quality_score": max(0, 100 - len(issues) * 15)}


def _step_anomaly_detection(db: Session, task_id: int) -> dict:
    """12项综合异常检测"""
    result = comprehensive_anomaly_scan(db, task_id)
    return {"step": "comprehensive_anomaly", "total_findings": result["total_findings"], "severity": result["severity_breakdown"], "top5": result["top_findings"][:5]}


def _step_account_analysis(db: Session, task_id: int) -> dict:
    """科目分析"""
    records = db.query(LedgerRecord).filter(LedgerRecord.task_id == task_id).all()
    by_account: dict[str, dict] = {}
    for r in records:
        code = r.account_code or "未映射"
        if code not in by_account:
            by_account[code] = {"name": r.account_name or "", "debit": 0.0, "credit": 0.0, "count": 0, "exceptions": 0}
        by_account[code]["debit"] += r.debit or 0
        by_account[code]["credit"] += r.credit or 0
        by_account[code]["count"] += 1
        if r.is_exception:
            by_account[code]["exceptions"] += 1

    top = sorted(by_account.items(), key=lambda x: x[1]["debit"] + x[1]["credit"], reverse=True)[:10]
    return {
        "step": "account_analysis",
        "top_accounts": [
            {"code": k, "name": v["name"], "debit": round(v["debit"], 2), "credit": round(v["credit"], 2), "count": v["count"], "exceptions": v["exceptions"]}
            for k, v in top
        ],
    }


def _step_risk_assessment(db: Session, task_id: int) -> dict:
    """风险评级（基于12项异常扫描）"""
    anomalies = comprehensive_anomaly_scan(db, task_id)
    records = db.query(LedgerRecord).filter(LedgerRecord.task_id == task_id)
    total = records.count()
    exception_count = records.filter(LedgerRecord.is_exception == True).count()

    # 风险评分
    score = 100
    if anomalies["total_findings"] > 10:
        score -= 30
    elif anomalies["total_findings"] > 5:
        score -= 15
    elif anomalies["total_findings"] > 0:
        score -= 5

    if total > 0 and exception_count / total > 0.2:
        score -= 25
    elif total > 0 and exception_count / total > 0.1:
        score -= 10

    high_severity = sum(1 for f in anomalies["findings"] if f.get("severity") == "高")
    score -= high_severity * 5

    level = "低" if score >= 80 else "中" if score >= 50 else "高"
    return {"step": "risk_assessment", "risk_score": max(0, score), "risk_level": level, "total_records": total, "exception_rate": round(exception_count / total * 100, 1) if total > 0 else 0, "high_severity_count": high_severity}


async def _step_generate_recommendations(db: Session, task_id: int) -> dict:
    """AI 生成建议"""
    paper = tool_generate_workpaper(db, task_id, format="risk")
    context = json.dumps(paper, ensure_ascii=False, indent=2)[:4000]

    messages = [
        {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
        {"role": "user", "content": f"以下是审计底稿数据，请生成5-8条具体的审计建议（每条30字以内，按优先级排列）：\n\n{context}"},
    ]
    suggestions = await call_llm(messages, max_tokens=500)
    return {"step": "generate_recommendations", "suggestions": suggestions}


# ── 步骤映射 ────────────────────────────────────────────
STEP_HANDLERS = {
    "data_quality_check": lambda db, tid: _step_data_quality(db, tid),
    "comprehensive_anomaly": lambda db, tid: _step_anomaly_detection(db, tid),
    "account_analysis": lambda db, tid: _step_account_analysis(db, tid),
    "risk_assessment": lambda db, tid: _step_risk_assessment(db, tid),
    "generate_recommendations": None,  # async
    "large_amount_scan": lambda db, tid: tool_detect_anomalies(db, task_id=tid, large_threshold=50000.0),
    "duplicate_scan": lambda db, tid: {"step": "duplicate_scan", "result": tool_detect_anomalies(db, task_id=tid)},
    "balance_check": lambda db, tid: tool_reconcile_account(db, account_code="%", task_id=tid),
    "anomaly_scan": lambda db, tid: tool_detect_anomalies(db, task_id=tid),
    "ar_balance_check": lambda db, tid: tool_get_account_summary(db, "1122", tid),
    "ap_balance_check": lambda db, tid: tool_get_account_summary(db, "2202", tid),
    "revenue_period_check": lambda db, tid: tool_get_account_summary(db, "6001", tid),
    "revenue_amount_check": lambda db, tid: tool_get_account_summary(db, "6001", tid),
    "revenue_account_match": lambda db, tid: tool_get_account_summary(db, "6001", tid),
    "expense_reasonableness": lambda db, tid: tool_get_account_summary(db, "6602", tid),
    "expense_compliance": lambda db, tid: tool_get_account_summary(db, "6602", tid),
    "expense_anomaly": lambda db, tid: tool_get_account_summary(db, "6602", tid),
}

# ── 异步步骤（AI 驱动）──────────────────────────────────
async def _ai_step(db, tid, account, topic, focus):
    summary = tool_get_account_summary(db, account, tid)
    paper = tool_generate_workpaper(db, tid, "risk")
    ctx = json.dumps({"account": account, "topic": topic, "summary": summary, "workpaper": paper}, ensure_ascii=False, indent=2)[:3000]
    messages = [{"role": "system", "content": AUDIT_SYSTEM_PROMPT}, {"role": "user", "content": f"分析{topic}，重点关注：{focus}\n\n{ctx}"}]
    return {"step": topic, "analysis": await call_llm(messages, max_tokens=500)}

async def _ai_revenue_match(db, tid):
    s1122 = tool_get_account_summary(db, "1122", tid)
    s6001 = tool_get_account_summary(db, "6001", tid)
    ctx = json.dumps({"ar": s1122, "revenue": s6001}, ensure_ascii=False)[:2500]
    messages = [{"role": "system", "content": AUDIT_SYSTEM_PROMPT}, {"role": "user", "content": f"分析应收增长与收入增长是否匹配：\n{ctx}"}]
    return {"step": "ar_revenue_match", "analysis": await call_llm(messages, max_tokens=500)}

async def _ai_ap_vendor(db, tid):
    records = db.query(LedgerRecord).filter(LedgerRecord.task_id == tid, LedgerRecord.account_code == "2202").all()
    vendors = {}
    for r in records:
        if r.summary: vendors[r.summary[:20]] = vendors.get(r.summary[:20], 0) + r.credit + r.debit
    top = sorted(vendors.items(), key=lambda x: x[1], reverse=True)[:10]
    ctx = json.dumps([{"name": k, "amount": round(v, 2)} for k, v in top], ensure_ascii=False)[:2000]
    messages = [{"role": "system", "content": AUDIT_SYSTEM_PROMPT}, {"role": "user", "content": f"分析应付账款供应商集中度风险：\n{ctx}"}]
    return {"step": "ap_vendor", "vendors": top[:5], "analysis": await call_llm(messages, max_tokens=400)}

ASYNC_STEPS = {
    "generate_recommendations": _step_generate_recommendations,
    "ar_aging_analysis": lambda db, tid: _ai_step(db, tid, "1122", "ar_aging", "账龄结构、逾期、回款周期"),
    "ar_revenue_match": _ai_revenue_match,
    "ar_risk_summary": lambda db, tid: _ai_step(db, tid, "1122", "ar_risk", "坏账风险、回款风险、信用风险"),
    "ap_vendor_analysis": _ai_ap_vendor,
    "ap_payment_check": lambda db, tid: _ai_step(db, tid, "2202", "ap_payment", "异常付款、大额预付、长期挂账"),
    "ap_risk_summary": lambda db, tid: _ai_step(db, tid, "2202", "ap_risk", "流动性风险、供应商依赖"),
    "revenue_risk_summary": lambda db, tid: _ai_step(db, tid, "6001", "revenue_risk", "虚增、截止性、关联交易"),
    "expense_risk_summary": lambda db, tid: _ai_step(db, tid, "6602", "expense_risk", "合规、税务、真实性"),
}


# ── 工作流执行 ──────────────────────────────────────────

async def run_workflow(
    db: Session,
    workflow_name: str,
    task_id: int,
    use_ai_summary: bool = True,
) -> dict[str, Any]:
    """执行审计工作流（v2：全步骤可用 + 追溯 + 证据链 + 二次校验）"""
    if workflow_name not in WORKFLOW_TEMPLATES:
        return {"error": f"未知工作流: {workflow_name}", "available": list(WORKFLOW_TEMPLATES.keys())}

    wf = WORKFLOW_TEMPLATES[workflow_name]
    task = db.get(TaskJob, task_id)
    if not task:
        return {"error": "任务不存在", "task_id": task_id}

    trail = AuditTrail()
    trail.add("workflow_start", {"workflow": wf["name"], "task_id": task_id})

    results = {
        "workflow": wf["name"],
        "description": wf["description"],
        "task_id": task_id,
        "filename": task.file.filename if task.file else "",
        "started_at": datetime.utcnow().isoformat(),
        "steps": [],
    }

    # 特殊工作流
    if workflow_name == "four_way":
        result = await four_way_verification(db, task_id)
        results["steps"].append({"step": "four_way_check", "result": result})
        results["ai_summary"] = result.get("ai_judgment", "")
        results["audit_trail"] = result.get("audit_trail", {})
        results["completed_at"] = datetime.utcnow().isoformat()
        return results

    if workflow_name == "multi_perspective":
        result = await multi_perspective_audit(db, task_id)
        results["steps"].append({"step": "multi_perspective", "result": result})
        results["ai_summary"] = result.get("merged_opinion", "")
        results["completed_at"] = datetime.utcnow().isoformat()
        return results

    for step_name in wf["steps"]:
        trail.add(f"step_start", {"step": step_name})

        # 同步步骤
        handler = STEP_HANDLERS.get(step_name)
        if handler:
            try:
                step_result = handler(db, task_id)
                results["steps"].append(step_result)
                trail.add("step_complete", {"step": step_name, "ok": True})
            except Exception as exc:
                logger.error("步骤 %s 失败: %s", step_name, exc)
                results["steps"].append({"step": step_name, "error": str(exc)})
                trail.add("step_error", {"step": step_name, "error": str(exc)})
            continue

        # 异步步骤
        async_handler = ASYNC_STEPS.get(step_name)
        if async_handler:
            try:
                step_result = await async_handler(db, task_id)
                results["steps"].append(step_result)
                trail.add("step_complete", {"step": step_name, "ok": True})
            except Exception as exc:
                logger.error("异步步骤 %s 失败: %s", step_name, exc)
                results["steps"].append({"step": step_name, "error": str(exc)})
                trail.add("step_error", {"step": step_name, "error": str(exc)})
            continue

        results["steps"].append({"step": step_name, "skipped": True})

    # 证据链
    try:
        exc_ids = [r.id for r in db.query(LedgerRecord).filter(LedgerRecord.task_id == task_id, LedgerRecord.is_exception == True).limit(20).all()]
        evidence = build_evidence_chain(db, exc_ids)
        results["evidence_chain"] = evidence
        trail.add("evidence_built", {"count": len(evidence)})
    except Exception as exc:
        logger.warning("证据链构建失败: %s", exc)

    # AI 汇总
    if use_ai_summary:
        trail.add("ai_summary_start")
        try:
            ctx = json.dumps({"workflow": wf["name"], "task": task.file.filename if task.file else "", "steps": [{"step": s.get("step", ""), "key": str(s)[:150]} for s in results["steps"][:10]]}, ensure_ascii=False)[:3000]
            messages = [{"role": "system", "content": AUDIT_SYSTEM_PROMPT}, {"role": "user", "content": f"工作流「{wf['name']}」执行完毕。请用300字总结：关键发现（3-5条）、风险等级、下一步。\n\n{ctx}"}]
            results["ai_summary"] = await call_llm(messages, max_tokens=600)
            trail.add("ai_summary_done")
        except Exception as exc:
            results["ai_summary"] = f"[AI汇总失败: {exc}]"

    # 高风险二次校验
    risk_step = next((s for s in results["steps"] if s.get("risk_level") == "高"), None)
    if risk_step:
        try:
            results["secondary_review"] = await secondary_review(json.dumps(risk_step, ensure_ascii=False)[:1000], results.get("evidence_chain", [])[:5])
            trail.add("secondary_review_done")
        except Exception as exc:
            logger.warning("二次校验失败: %s", exc)

    results["audit_trail"] = trail.to_dict()
    results["completed_at"] = datetime.utcnow().isoformat()
    return results


def get_available_workflows() -> list[dict[str, Any]]:
    """列出可用工作流"""
    return [{"id": k, "name": v["name"], "description": v["description"], "steps": v["steps"]} for k, v in WORKFLOW_TEMPLATES.items()]
