"""AI 模块配置 —— 模型、向量库、合规策略"""
from __future__ import annotations

import os
from pathlib import Path

# ── 向量库 ──────────────────────────────────────────────
AI_DIR = Path(__file__).resolve().parent
VECTOR_STORE_DIR = AI_DIR / "vector_store"
VECTOR_INDEX_NAME = os.getenv("AI_VECTOR_INDEX", "audit_index")
EMBEDDING_DIM = int(os.getenv("AI_EMBEDDING_DIM", "384"))  # all-MiniLM-L6-v2 = 384
TOP_K_DEFAULT = int(os.getenv("AI_TOP_K", "10"))

# ── Embedding 模型（本地优先） ─────────────────────────
EMBEDDING_MODEL = os.getenv("AI_EMBED_MODEL", "all-MiniLM-L6-v2")
# 多模态模型（图像+文本联合嵌入）
MULTIMODAL_MODEL = os.getenv("AI_MM_MODEL", "clip-ViT-B-32")

# ── LLM / RAG 生成 ─────────────────────────────────────
LLM_PROVIDER = os.getenv("AI_LLM_PROVIDER", "zhipu")
LLM_MODEL = os.getenv("AI_LLM_MODEL", "glm-4.5-air")
LLM_API_KEY = os.getenv("AI_LLM_API_KEY", "4eec6eee17284dd281bfcdb6b66850ee.BortzTjmpejDWDvX")
LLM_BASE_URL = os.getenv("AI_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_MAX_TOKENS = int(os.getenv("AI_LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.getenv("AI_LLM_TEMPERATURE", "0.3"))

# ── 文档分块 ───────────────────────────────────────────
CHUNK_SIZE = int(os.getenv("AI_CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("AI_CHUNK_OVERLAP", "50"))

# ── 合规与访问控制 ─────────────────────────────────────
AI_ACCESS_ENABLED = os.getenv("AI_ACCESS_ENABLED", "true").lower() == "true"
AI_AUDIT_LOG_ENABLED = os.getenv("AI_AUDIT_LOG_ENABLED", "true").lower() == "true"
AI_PII_MASK_ENABLED = os.getenv("AI_PII_MASK_ENABLED", "true").lower() == "true"
AI_RATE_LIMIT_PER_MIN = int(os.getenv("AI_RATE_LIMIT", "30"))

# ── 自动建议 ───────────────────────────────────────────
AI_SUGGESTION_ENABLED = os.getenv("AI_SUGGESTION_ENABLED", "true").lower() == "true"
AI_SUGGESTION_THRESHOLD = float(os.getenv("AI_SUGGESTION_THRESHOLD", "0.75"))

# 确保目录存在
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
