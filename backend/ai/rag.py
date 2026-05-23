"""RAG 引擎 —— 检索增强生成

支持:
- 基于向量检索的上下文构建
- Deep Seek / OpenAI / Ollama 等多 LLM 后端
- 审计专用 Prompt 模板
- 带引用的答案生成
- 流式与非流式响应
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, AsyncGenerator

import httpx

from .config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    TOP_K_DEFAULT,
)
from .embeddings import embed_text
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)

# ── 审计 Prompt 模板 ────────────────────────────────────
AUDIT_SYSTEM_PROMPT = """你是一位资深的财务审计专家，拥有 CPA 资格和 15 年审计经验。
你的任务是基于提供的审计数据上下文，回答用户的问题。

## 核心原则
1. **仅基于上下文回答**：如果你的回答引用上下文中的具体数据，请注明来源（如记录 ID、科目编码）。
2. **保持专业与谨慎**：使用规范的财务审计术语，对不确定的内容明确标注"据现有数据推断"。
3. **结构化输出**：优先使用分点、表格等结构化方式呈现分析结果。
4. **风险提示**：如发现潜在审计风险（金额异常、科目不匹配、凭证缺失等），请主动指出。
5. **不编造**：如果上下文信息不足以回答问题，请明确说明，不要编造数据。"""

# ── LLM 调用 ────────────────────────────────────────────


async def call_llm(
    messages: list[dict[str, str]],
    model: str = LLM_MODEL,
    max_tokens: int = LLM_MAX_TOKENS,
    temperature: float = LLM_TEMPERATURE,
    stream: bool = False,
) -> str | AsyncGenerator[str, None]:
    """调用 LLM（支持 Deep Seek / OpenAI 兼容 API）"""
    api_key = LLM_API_KEY
    base_url = LLM_BASE_URL.rstrip("/")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        if stream:
            return _stream_response(client, base_url, headers, payload)
        else:
            return await _sync_response(client, base_url, headers, payload)


async def _sync_response(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> str:
    """非流式响应"""
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        # GLM-4.5 推理模型：content 可能为空，用 reasoning_content 兜底
        content = msg.get("content", "") or msg.get("reasoning_content", "")
        return content if content else "[模型返回空内容]"
    except Exception as exc:
        logger.error("LLM 调用失败: %s", exc)
        return f"[LLM 调用失败: {exc}]"


async def _stream_response(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> AsyncGenerator[str, None]:
    """流式响应生成器"""
    try:
        async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "") or delta.get("reasoning_content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:
        logger.error("流式 LLM 调用失败: %s", exc)
        yield f"\n[LLM 流式调用失败: {exc}]"


# ── 本地回退 ────────────────────────────────────────────
def _local_response(question: str, context_texts: list[str]) -> str:
    """当 LLM 不可用时的本地回退 —— 基于关键词匹配和规则"""
    ctx = "\n".join(context_texts[:5]) if context_texts else "无上下文"

    # 简单关键词响应
    q = question.lower()
    if "异常" in q or "风险" in q:
        return f"""## 审计风险提示（本地分析）

基于检索到的 {len(context_texts)} 条关联记录，以下为初步风险分析：

> ⚠️ **注意**：当前未配置 LLM API，无法生成深度分析。以下为基于规则的初步结果。

**上下文摘要**：
{ctx[:500]}

**建议**：
1. 配置 Deep Seek API Key（环境变量 `AI_LLM_API_KEY`）以启用 AI 深度分析
2. 手动检查上述上下文中的金额和科目匹配情况
"""
    elif "汇总" in q or "统计" in q:
        return f"""## 数据汇总（本地分析）

检索到 {len(context_texts)} 条相关记录。

> 📌 当前为本地规则分析模式，配置 LLM 后可获得更详细的分析。

**上下文片段**：
{ctx[:800]}
"""
    else:
        return f"""## 检索结果

基于您的查询，检索到 {len(context_texts)} 条相关审计记录。

> 💡 **提示**：配置 Deep Seek API Key 后，AI 可对这些结果进行深度分析和建议。

**Top 3 结果**：
{ctx[:600]}
"""


# ── RAG 核心 ────────────────────────────────────────────


def _build_context(search_results: list[dict[str, Any]], max_tokens: int = 3000) -> str:
    """从检索结果构建 LLM 上下文"""
    parts = []
    total_chars = 0
    for i, r in enumerate(search_results[:10]):
        snippet = f"[来源 {i + 1}] 相似度: {r['score']:.3f}\n"
        meta = r.get("metadata", {})
        if meta.get("account_code"):
            snippet += f"科目: {meta['account_code']} {meta.get('account_name', '')}\n"
        if meta.get("voucher_no"):
            snippet += f"凭证号: {meta['voucher_no']}\n"
        if meta.get("record_date"):
            snippet += f"日期: {meta['record_date']}\n"
        snippet += f"内容: {r['text']}\n---\n"
        if total_chars + len(snippet) > max_tokens * 4:  # 中文字符估算
            break
        parts.append(snippet)
        total_chars += len(snippet)

    return "\n".join(parts) if parts else "未找到相关审计数据。"


async def rag_query(
    question: str,
    top_k: int = TOP_K_DEFAULT,
    filters: dict[str, Any] | None = None,
    use_llm: bool = True,
    stream: bool = False,
) -> dict[str, Any]:
    """RAG 问答核心流程：检索 → 构建上下文 → LLM 生成"""
    store = get_vector_store()

    # Step 1: 语义检索
    query_vec = embed_text(question)
    search_results = store.search(query_vec, top_k=top_k, filters=filters)

    # Step 2: 构建上下文
    context = _build_context(search_results)

    # Step 3: 生成回答
    if use_llm and LLM_API_KEY:
        messages = [
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""## 审计数据上下文

{context}

## 用户问题

{question}

请基于上述审计数据上下文，给出专业、结构化的回答。""",
            },
        ]
        answer = await call_llm(messages, stream=stream)
    else:
        answer = _local_response(question, [r["text"] for r in search_results])

    return {
        "question": question,
        "answer": answer if isinstance(answer, str) else "[流式响应]",
        "sources": [
            {
                "id": r["id"],
                "text": r["text"][:300],
                "score": r["score"],
                "metadata": r.get("metadata", {}),
                "modality": r.get("modality", "text"),
            }
            for r in search_results[:5]
        ],
        "context_length": len(context),
        "model": LLM_MODEL if (use_llm and LLM_API_KEY) else "local-fallback",
        "stream": stream,
    }


async def rag_query_stream(
    question: str,
    top_k: int = TOP_K_DEFAULT,
    filters: dict[str, Any] | None = None,
) -> AsyncGenerator[str, None]:
    """RAG 流式问答"""
    store = get_vector_store()
    query_vec = embed_text(question)
    search_results = store.search(query_vec, top_k=top_k, filters=filters)
    context = _build_context(search_results)

    if LLM_API_KEY:
        messages = [
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {"role": "user", "content": f"## 审计数据上下文\n\n{context}\n\n## 用户问题\n\n{question}\n\n请基于上述上下文给出回答。"},
        ]
        # 先发送来源信息
        sources_header = f"📋 **检索到 {len(search_results)} 条相关记录**\n\n"
        yield sources_header
        async for chunk in await call_llm(messages, stream=True):
            yield chunk
    else:
        answer = _local_response(question, [r["text"] for r in search_results])
        yield answer


def rag_health() -> dict[str, Any]:
    """RAG 服务状态检查"""
    store = get_vector_store()
    return {
        "vector_store": store.stats(),
        "llm_provider": LLM_PROVIDER,
        "llm_model": LLM_MODEL,
        "llm_configured": bool(LLM_API_KEY),
        "llm_base_url": LLM_BASE_URL,
    }
