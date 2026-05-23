"""AI 模块 API 路由

提供:
- /api/ai/health           — AI 服务状态
- /api/ai/search           — 语义搜索
- /api/ai/qa               — RAG 问答
- /api/ai/qa/stream        — 流式 RAG 问答
- /api/ai/suggestions      — 自动审计建议
- /api/ai/index            — 触发索引
- /api/ai/index/status     — 索引状态
- /api/ai/feedback         — 人工反馈
- /api/ai/admin/info       — 管理信息
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..database import SessionLocal, get_db
from sqlalchemy.orm import Session

from .auth import (
    ai_auth_dependency,
    ai_rate_limit_dependency,
    audit_log,
    check_permission,
    get_api_key_info,
    with_audit,
    _hash_key,
)
from .embeddings import embeddings_health
from .indexer import index_ledger_records, index_ocr_results, index_status, reindex_all
from .rag import rag_health, rag_query, rag_query_stream
from .suggestions import generate_suggestions
from .vector_store import get_vector_store
from .tools import TOOL_DEFINITIONS, execute_tool
from .workflows import run_workflow, get_available_workflows, WORKFLOW_TEMPLATES
from .workpapers import generate_workpaper_docx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["AI"])


# ── 请求模型 ────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询文本", min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    modality: str | None = Field(default=None, pattern="^(text|image|fused)$")
    filters: dict[str, Any] | None = None


class QARequest(BaseModel):
    question: str = Field(..., description="审计问题", min_length=1, max_length=4000)
    task_id: int | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    use_llm: bool = True


class FeedbackRequest(BaseModel):
    query_id: str = Field(..., description="查询标识")
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    notes: str = Field(default="", max_length=1000)
    correct_answer: str = Field(default="", max_length=4000, description="人工纠正答案（可选）")


class IndexRequest(BaseModel):
    task_id: int | None = None
    force: bool = False
    include_images: bool = True


class ToolCallRequest(BaseModel):
    name: str = Field(..., description="工具名称")
    arguments: dict[str, Any] = Field(default_factory=dict)


class WorkflowRequest(BaseModel):
    workflow_name: str = Field(..., description="工作流名称")
    task_id: int = Field(..., description="任务 ID")
    use_ai_summary: bool = True


class WorkpaperRequest(BaseModel):
    task_id: int = Field(..., description="任务 ID")
    format: str = Field(default="standard", pattern="^(standard|risk|detail)$")


# ── 路由 ────────────────────────────────────────────────
@router.get("/health", dependencies=[])
async def ai_health_public():
    """AI 模块健康检查（公开端点，无需认证）"""
    return {
        "status": "ok",
        "embeddings": embeddings_health(),
        "rag": rag_health(),
        "access": {"enabled": True, "note": "请在请求中提供 Authorization: Bearer <your-api-key> 以使用受限功能"},
    }


@router.post("/search")
async def semantic_search(
    req: SearchRequest,
    request: Request,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
):
    """语义搜索 —— 基于向量相似度检索审计数据"""
    if not check_permission(api_key, "search"):
        raise HTTPException(status_code=403, detail="无搜索权限")

    audit_log("semantic_search", _hash_key(api_key), {"query": req.query[:100], "top_k": req.top_k})

    store = get_vector_store()
    if store.count == 0:
        return {"results": [], "total": 0, "message": "索引为空，请先上传数据并触发索引"}

    from .embeddings import embed_text

    query_vec = embed_text(req.query)
    results = store.search(query_vec, top_k=req.top_k, filters=req.filters, modality=req.modality)

    return {"results": results, "total": len(results), "query": req.query[:200]}


@router.post("/qa")
async def ai_qa(
    req: QARequest,
    request: Request,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
):
    """AI 审计问答 —— RAG 检索增强生成"""
    if not check_permission(api_key, "qa"):
        raise HTTPException(status_code=403, detail="无问答权限")

    audit_log("ai_qa", _hash_key(api_key), {"question": req.question[:150]})

    filters = {"task_id": req.task_id} if req.task_id else None
    result = await rag_query(
        question=req.question,
        top_k=req.top_k,
        filters=filters,
        use_llm=req.use_llm,
        stream=False,
    )
    return result


@router.post("/qa/stream")
async def ai_qa_stream(
    req: QARequest,
    request: Request,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
):
    """流式 AI 审计问答"""
    if not check_permission(api_key, "qa"):
        raise HTTPException(status_code=403, detail="无问答权限")

    audit_log("ai_qa_stream", _hash_key(api_key), {"question": req.question[:150]})

    filters = {"task_id": req.task_id} if req.task_id else None

    async def generate():
        async for chunk in rag_query_stream(req.question, top_k=req.top_k, filters=filters):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@router.get("/suggestions")
async def audit_suggestions(
    task_id: int | None = None,
    use_llm: bool = False,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
    db: Session = Depends(get_db),
):
    """自动审计建议"""
    if not check_permission(api_key, "suggestions"):
        raise HTTPException(status_code=403, detail="无建议权限")

    audit_log("suggestions", _hash_key(api_key), {"task_id": task_id})

    result = await generate_suggestions(db, task_id=task_id, use_llm=use_llm)
    return result


@router.post("/index")
async def trigger_index(
    req: IndexRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
):
    """触发数据索引（后台任务）"""
    if not check_permission(api_key, "reindex"):
        raise HTTPException(status_code=403, detail="无索引管理权限")

    audit_log("trigger_index", _hash_key(api_key), {"task_id": req.task_id, "force": req.force})

    def _run_index():
        db = SessionLocal()
        try:
            ledger_result = index_ledger_records(db, task_id=req.task_id, force=req.force)
            ocr_result = index_ocr_results(db, task_id=req.task_id, include_images=req.include_images, force=req.force)
            logger.info("索引完成: ledger=%s, ocr=%s", ledger_result, ocr_result)
        finally:
            db.close()

    background_tasks.add_task(_run_index)
    return {"status": "queued", "message": "索引任务已加入后台队列"}


@router.post("/index/reindex-all")
async def reindex_all_data(
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
):
    """全量重建索引"""
    if not check_permission(api_key, "reindex"):
        raise HTTPException(status_code=403, detail="无索引管理权限")

    audit_log("reindex_all", _hash_key(api_key))

    db = SessionLocal()
    try:
        result = reindex_all(db)
        return result
    finally:
        db.close()


@router.get("/index/status", dependencies=[])
async def get_index_status_public():
    """查询索引状态（公开端点）"""
    return index_status()


@router.post("/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    request: Request,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
):
    """提交人工反馈"""
    if not check_permission(api_key, "feedback"):
        raise HTTPException(status_code=403, detail="无反馈权限")

    audit_log(
        "feedback",
        _hash_key(api_key),
        {"query_id": req.query_id, "rating": req.rating, "notes": req.notes[:200]},
    )

    # 保存反馈到文件（后续可用于微调）
    from pathlib import Path
    import json

    feedback_dir = Path(__file__).resolve().parent / "feedback"
    feedback_dir.mkdir(exist_ok=True)
    feedback_file = feedback_dir / "feedback.jsonl"

    entry = {
        "query_id": req.query_id,
        "rating": req.rating,
        "notes": req.notes,
        "correct_answer": req.correct_answer,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
    }
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok", "message": "反馈已记录，感谢您的贡献！"}


@router.get("/admin/info")
async def admin_info(
    api_key: str = Depends(ai_auth_dependency),
):
    """管理员信息面板"""
    if not check_permission(api_key, "admin"):
        raise HTTPException(status_code=403, detail="无管理权限")

    store = get_vector_store()
    return {
        "vector_store": store.stats(),
        "embeddings": embeddings_health(),
        "rag": rag_health(),
        "api_key_info": get_api_key_info(api_key),
    }


# ══════════════════════════════════════════════════════════
# 工具调用 & 工作流 & 底稿  ── 新增
# ══════════════════════════════════════════════════════════

@router.get("/tools")
async def list_tools(
    api_key: str = Depends(ai_auth_dependency),
):
    """列出 AI 可调用的工具清单"""
    return {"tools": TOOL_DEFINITIONS, "total": len(TOOL_DEFINITIONS)}


@router.post("/tools/execute")
async def call_tool(
    req: ToolCallRequest,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
    db: Session = Depends(get_db),
):
    """执行 AI 工具调用（查账/对账/异常检测/底稿生成等）"""
    if not check_permission(api_key, "qa"):
        raise HTTPException(status_code=403, detail="无权限")
    audit_log("tool_call", _hash_key(api_key), {"tool": req.name, "args": str(req.arguments)[:200]})
    result = execute_tool(req.name, req.arguments, db)
    return {"tool": req.name, "result": result}


@router.get("/workflows")
async def list_workflows(
    api_key: str = Depends(ai_auth_dependency),
):
    """列出可用审计工作流"""
    return {"workflows": get_available_workflows()}


@router.post("/workflows/run")
async def execute_workflow(
    req: WorkflowRequest,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
    db: Session = Depends(get_db),
):
    """执行审计工作流（全面/应收/应付/收入/费用/快速扫描）"""
    if not check_permission(api_key, "qa"):
        raise HTTPException(status_code=403, detail="无权限")

    if req.workflow_name not in WORKFLOW_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"未知工作流: {req.workflow_name}。可用: {list(WORKFLOW_TEMPLATES.keys())}")

    audit_log("workflow_run", _hash_key(api_key), {"workflow": req.workflow_name, "task_id": req.task_id})
    result = await run_workflow(db, req.workflow_name, req.task_id, req.use_ai_summary)
    return result


@router.post("/workpapers/generate")
async def generate_workpaper(
    req: WorkpaperRequest,
    api_key: str = Depends(ai_auth_dependency),
    _rate: None = Depends(ai_rate_limit_dependency),
    db: Session = Depends(get_db),
):
    """生成审计底稿 Word 文档"""
    if not check_permission(api_key, "export"):
        raise HTTPException(status_code=403, detail="无权限")

    audit_log("workpaper_generate", _hash_key(api_key), {"task_id": req.task_id, "format": req.format})
    try:
        path = generate_workpaper_docx(db, req.task_id, req.format)
        return {
            "status": "ok",
            "path": str(path),
            "filename": path.name,
            "message": "审计底稿已生成",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")
