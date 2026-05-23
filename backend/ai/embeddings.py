"""Embedding 引擎 —— 文本嵌入 + 多模态（CLIP）嵌入

支持:
- 纯文本嵌入 (sentence-transformers)
- 图像嵌入 (CLIP ViT-B/32)
- 批量嵌入与缓存
- PII 脱敏预处理
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from .config import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    MULTIMODAL_MODEL,
    AI_PII_MASK_ENABLED,
    VECTOR_STORE_DIR,
)

logger = logging.getLogger(__name__)

# ── 模型懒加载 ──────────────────────────────────────────
_text_model = None
_image_model = None


def _get_text_model():
    """延迟加载 sentence-transformers 文本模型"""
    global _text_model
    if _text_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _text_model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("文本 Embedding 模型已加载: %s", EMBEDDING_MODEL)
        except ImportError:
            logger.warning("sentence-transformers 未安装，使用伪嵌入回退")
            _text_model = _FallbackEmbedder(EMBEDDING_DIM)
        except Exception as exc:
            logger.error("加载文本模型失败: %s", exc)
            _text_model = _FallbackEmbedder(EMBEDDING_DIM)
    return _text_model


def _get_image_model():
    """延迟加载 CLIP 图像模型"""
    global _image_model
    if _image_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _image_model = SentenceTransformer(MULTIMODAL_MODEL)
            logger.info("多模态 Embedding 模型已加载: %s", MULTIMODAL_MODEL)
        except ImportError:
            logger.warning("sentence-transformers 未安装，图像嵌入不可用")
            _image_model = None
        except Exception as exc:
            logger.warning("加载多模态模型失败 (%s)，图像嵌入降级为文本模型", exc)
            _image_model = _get_text_model()
    return _image_model


class _FallbackEmbedder:
    """当 sentence-transformers 不可用时的伪嵌入回退（基于字符 n-gram hash）"""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def encode(self, texts: list[str] | str, **kwargs: Any) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for n in (2, 3, 4):
                for j in range(len(t) - n + 1):
                    h = int(hashlib.md5(t[j : j + n].encode()).hexdigest(), 16)
                    vectors[i, h % self.dim] += 1.0
            norm = np.linalg.norm(vectors[i])
            if norm > 0:
                vectors[i] /= norm
        return vectors


# ── PII 脱敏 ────────────────────────────────────────────
PII_PATTERNS = [
    (re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"), "[身份证号]"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "[手机号]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[邮箱]"),
    (re.compile(r"\b\d{16,19}\b"), "[银行卡号]"),
    (re.compile(r"\b(?:[\d]{3,4}[- ]?){3,4}\b"), "[号码]"),
]


def mask_pii(text: str) -> str:
    """脱敏个人隐私信息"""
    if not AI_PII_MASK_ENABLED:
        return text
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ── 文本分块 ────────────────────────────────────────────
from .config import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """将长文本切分为重叠块"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ── 嵌入 API ────────────────────────────────────────────
@lru_cache(maxsize=512)
def _cached_embed(text: str) -> tuple:
    """带缓存的文本嵌入（内部用 tuple 可哈希）"""
    vec = _get_text_model().encode([mask_pii(text)], show_progress_bar=False)
    return tuple(vec[0].tolist())


def embed_text(text: str | list[str]) -> np.ndarray:
    """文本嵌入（支持单条或批量）"""
    if isinstance(text, str):
        vec = _cached_embed(text)
        return np.array(vec, dtype=np.float32)
    # 批量嵌入
    masked = [mask_pii(t) for t in text]
    return _get_text_model().encode(masked, show_progress_bar=False)


def embed_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict[str, Any]]:
    """文本分块后逐块嵌入，返回带元数据的列表"""
    chunks = chunk_text(text, chunk_size, overlap)
    if not chunks:
        return []
    vectors = _get_text_model().encode([mask_pii(c) for c in chunks], show_progress_bar=False)
    return [
        {
            "chunk_index": i,
            "text": chunks[i],
            "vector": vectors[i].tolist(),
            "char_start": max(0, i * (chunk_size - overlap)),
            "char_end": min(len(text), i * (chunk_size - overlap) + len(chunks[i])),
        }
        for i in range(len(chunks))
    ]


def embed_image(image_path: str | Path) -> np.ndarray | None:
    """图像嵌入（CLIP 多模态）"""
    model = _get_image_model()
    if model is None or isinstance(model, _FallbackEmbedder):
        return None
    try:
        from PIL import Image

        img = Image.open(image_path).convert("RGB")
        vec = model.encode([img], show_progress_bar=False)
        return vec[0]
    except Exception as exc:
        logger.warning("图像嵌入失败 %s: %s", image_path, exc)
        return None


def embed_ocr_image(image_path: str | Path, ocr_text: str) -> np.ndarray:
    """组合嵌入：图像嵌入 + OCR 文本嵌入的加权融合"""
    img_vec = embed_image(image_path)
    txt_vec = embed_text(ocr_text[:500])  # 截取前500字符

    if img_vec is not None:
        # 加权融合：图像 0.6 + 文本 0.4
        fused = img_vec * 0.6 + txt_vec * 0.4
        norm = np.linalg.norm(fused)
        if norm > 0:
            fused /= norm
        return fused
    return txt_vec


def embeddings_health() -> dict[str, Any]:
    """检查嵌入服务状态"""
    text_ok = True
    image_ok = True
    text_error = None
    image_error = None

    try:
        _get_text_model()
    except Exception as e:
        text_ok = False
        text_error = str(e)

    try:
        m = _get_image_model()
        if m is None or isinstance(m, _FallbackEmbedder):
            image_ok = False
            image_error = "多模态模型不可用"
    except Exception as e:
        image_ok = False
        image_error = str(e)

    return {
        "text_embedding": {"available": text_ok, "model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "error": text_error},
        "image_embedding": {"available": image_ok, "model": MULTIMODAL_MODEL, "error": image_error},
        "pii_mask_enabled": AI_PII_MASK_ENABLED,
        "chunk_config": {"chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP},
    }
