"""多视角审计引擎 —— 三种审计视角分别输出

支持:
- 风险审计视角（Risk Audit）
- 合规审计视角（Compliance Audit）
- 业务复核视角（Business Review）
- 三视角综合汇总
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import LedgerRecord, TaskJob
from .rag import call_llm, AUDIT_SYSTEM_PROMPT
from .tools import tool_get_account_summary, tool_detect_anomalies, tool_generate_workpaper

logger = logging.getLogger(__name__)


PERSPECTIVE_PROMPTS = {
    "risk": """你是一位风险导向审计师（Risk-Based Auditor）。
重点关注：
1. 重大错报风险（固有风险、控制风险）
2. 舞弊风险信号（管理层凌驾、关联交易）
3. 异常波动和不合理趋势
4. 超出重要性水平的错报
5. 高风险科目和交易

请用风险审计视角输出，使用"高风险/中风险/低风险"标注。""",

    "compliance": """你是一位合规审计师（Compliance Auditor）。
重点关注：
1. 会计准则遵从性（企业会计准则）
2. 内部控制有效性
3. 审批流程合规性
4. 凭证完整性和规范性
5. 披露要求达标情况

请用合规审计视角输出，使用"不合规/需改进/合规"标注。""",

    "business": """你是一位业务复核师（Business Reviewer）。
重点关注：
1. 交易商业实质（Business Purpose）
2. 金额与业务规模匹配性
3. 供应商/客户合理性
4. 价格公允性
5. 业务逻辑自洽性

请用业务复核视角输出，使用"需关注/合理/待确认"标注。""",
}


async def multi_perspective_audit(
    db: Session,
    task_id: int,
    account_code: str | None = None,
) -> dict:
    """执行三视角并行审计"""
    task = db.get(TaskJob, task_id)
    if not task:
        return {"error": "任务不存在"}

    # 获取审计数据上下文
    summary = tool_get_account_summary(db, account_code or "1122", task_id)
    anomalies = tool_detect_anomalies(db, task_id)
    workpaper = tool_generate_workpaper(db, task_id, "risk")

    audit_context = json.dumps({
        "task": task.file.filename if task.file else "",
        "account_summary": summary,
        "anomalies": {"total": anomalies["total_findings"], "top5": anomalies["findings"][:5]},
        "workpaper": workpaper,
    }, ensure_ascii=False, indent=2)[:4000]

    results = {}
    perspectives = []

    for key, system_prompt in PERSPECTIVE_PROMPTS.items():
        try:
            messages = [
                {"role": "system", "content": system_prompt + "\n\n" + AUDIT_SYSTEM_PROMPT},
                {"role": "user", "content": f"请从你的视角分析以下审计数据，输出核心发现（3-5条，每条带评级标注）：\n\n{audit_context}"},
            ]
            answer = await call_llm(messages, max_tokens=500)
            results[key] = answer
            perspectives.append({"perspective": key, "label": {"risk": "风险审计", "compliance": "合规审计", "business": "业务复核"}[key], "analysis": answer})
        except Exception as exc:
            logger.error("视角 %s 分析失败: %s", key, exc)
            results[key] = f"[分析失败: {exc}]"

    # 综合汇总
    merge_context = "\n\n".join(f"=== {k}视角 ===\n{v[:300]}" for k, v in results.items())
    messages = [
        {"role": "system", "content": "你是审计项目经理，需要综合三个视角的分析，输出最终审计意见。"},
        {"role": "user", "content": f"请综合以下三个视角的分析，输出：\n1. 综合风险等级\n2. 需立即处理的事项（按优先级）\n3. 综合审计意见\n\n{merge_context}"},
    ]
    merged = await call_llm(messages, max_tokens=500)

    return {
        "task_id": task_id,
        "perspectives": perspectives,
        "merged_opinion": merged,
        "generated_at": datetime.utcnow().isoformat(),
    }
