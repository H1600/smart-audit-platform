"""向量存储 —— FAISS 索引 + 元数据管理

支持:
- FAISS 扁平索引 (L2 / 内积)
- 带元数据过滤的检索
- 增量增删
- 持久化到磁盘
- 多模态向量存储（文本 + 图像）
"""
from __future__ import annotations

import json
import logging
import pickle
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .config import EMBEDDING_DIM, TOP_K_DEFAULT, VECTOR_STORE_DIR, VECTOR_INDEX_NAME

logger = logging.getLogger(__name__)

# ── 延迟导入 FAISS ─────────────────────────────────────
_faiss = None


def _get_faiss():
    global _faiss
    if _faiss is None:
        try:
            import faiss as f

            _faiss = f
            logger.info("FAISS 已加载")
        except ImportError:
            logger.warning("FAISS 未安装，使用 numpy 回退")
            _faiss = _NumpyIndex  # type: ignore[assignment]
    return _faiss


class _NumpyIndex:
    """FAISS 的 NumPy 回退实现 —— 仅适用于小规模数据（< 10k 条）"""

    def __init__(self, vectors: np.ndarray | None = None):
        self.vectors = vectors if vectors is not None else np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    def add(self, vectors: np.ndarray):
        self.vectors = np.vstack([self.vectors, vectors])

    def search(self, query: np.ndarray, k: int = TOP_K_DEFAULT):
        if len(self.vectors) == 0:
            return np.empty((query.shape[0], 0), dtype=np.float32), np.empty((query.shape[0], 0), dtype=np.int64)
        # 内积相似度
        scores = np.dot(query, self.vectors.T)
        k = min(k, len(self.vectors))
        indices = np.argsort(-scores, axis=1)[:, :k]
        top_scores = np.take_along_axis(scores, indices, axis=1)
        return top_scores.astype(np.float32), indices.astype(np.int64)

    def reset(self):
        self.vectors = np.empty((0, EMBEDDING_DIM), dtype=np.float32)


@dataclass
class VectorRecord:
    """向量存储记录"""

    id: str  # 唯一标识
    vector: list[float]  # 嵌入向量
    text: str  # 原始文本片段
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据（task_id, file_id, page 等）
    modality: str = "text"  # text | image | fused
    indexed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class VectorStore:
    """FAISS 向量存储封装"""

    def __init__(self, dim: int = EMBEDDING_DIM, index_name: str = VECTOR_INDEX_NAME):
        self.dim = dim
        self.index_name = index_name
        self.index_path = VECTOR_STORE_DIR / f"{index_name}.faiss"
        self.meta_path = VECTOR_STORE_DIR / f"{index_name}.meta.jsonl"
        self._index = None
        self._records: list[VectorRecord] = []
        self._load()

    # ── 索引管理 ────────────────────────────────────────
    def _create_index(self):
        faiss = _get_faiss()
        if faiss is _NumpyIndex:
            self._index = _NumpyIndex()
        else:
            self._index = faiss.IndexFlatIP(self.dim)  # 内积 = 余弦相似度（归一化后）

    def _load(self):
        """从磁盘加载索引和元数据"""
        faiss = _get_faiss()
        if self.index_path.exists() and faiss is not _NumpyIndex:
            try:
                self._index = faiss.read_index(str(self.index_path))
                logger.info("已加载 FAISS 索引: %s (%d 条)", self.index_path, self._index.ntotal)
            except Exception as exc:
                logger.warning("加载索引失败, 重新创建: %s", exc)
                self._create_index()
        else:
            self._create_index()

        # 加载元数据
        if self.meta_path.exists():
            with open(self.meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            self._records.append(VectorRecord(**data))
                        except Exception:
                            pass
            logger.info("已加载 %d 条元数据记录", len(self._records))

    def save(self):
        """持久化索引和元数据"""
        faiss = _get_faiss()
        if faiss is not _NumpyIndex and self._index is not None:
            faiss.write_index(self._index, str(self.index_path))
            logger.info("FAISS 索引已保存: %s", self.index_path)

        with open(self.meta_path, "w", encoding="utf-8") as f:
            for rec in self._records:
                f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        logger.info("元数据已保存: %s (%d 条)", self.meta_path, len(self._records))

    # ── 增删 ────────────────────────────────────────────
    def add(
        self,
        vectors: np.ndarray,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
        modality: str = "text",
    ) -> list[str]:
        """批量添加向量"""
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        if vectors.shape[1] != self.dim:
            raise ValueError(f"向量维度不匹配: {vectors.shape[1]} != {self.dim}")

        # 归一化（用于内积→余弦相似度）
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms

        faiss = _get_faiss()
        self._index.add(vectors)

        n = vectors.shape[0]
        added_ids = []
        for i in range(n):
            vid = ids[i] if ids and i < len(ids) else f"vec_{int(time.time() * 1000)}_{i}_{len(self._records)}"
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            rec = VectorRecord(
                id=vid,
                vector=vectors[i].tolist(),
                text=texts[i] if i < len(texts) else "",
                metadata=meta,
                modality=modality,
            )
            self._records.append(rec)
            added_ids.append(vid)

        self.save()
        return added_ids

    def remove(self, ids: list[str]) -> int:
        """按 ID 删除记录（重建索引）"""
        before = len(self._records)
        remove_set = set(ids)
        self._records = [r for r in self._records if r.id not in remove_set]
        removed = before - len(self._records)

        if removed > 0:
            self._rebuild_index()
        return removed

    def _rebuild_index(self):
        """从 records 重建 FAISS 索引"""
        self._create_index()
        if self._records:
            vectors = np.array([r.vector for r in self._records], dtype=np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors = vectors / norms
            self._index.add(vectors)
        self.save()

    # ── 检索 ────────────────────────────────────────────
    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = TOP_K_DEFAULT,
        filters: dict[str, Any] | None = None,
        modality: str | None = None,
    ) -> list[dict[str, Any]]:
        """语义检索 + 元数据过滤"""
        if query_vector.ndim == 1:
            query_vector = query_vector.reshape(1, -1)

        # 归一化
        norm = np.linalg.norm(query_vector)
        if norm > 0:
            query_vector = query_vector / norm

        # FAISS 检索（多取一些，用于后续过滤）
        search_k = min(top_k * 3 if filters or modality else top_k, len(self._records))
        if search_k == 0:
            return []

        scores, indices = self._index.search(query_vector, search_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._records):
                continue
            rec = self._records[idx]

            # 模态过滤
            if modality and rec.modality != modality:
                continue

            # 元数据过滤
            if filters:
                match = True
                for key, value in filters.items():
                    if key not in rec.metadata or rec.metadata[key] != value:
                        match = False
                        break
                if not match:
                    continue

            results.append(
                {
                    "id": rec.id,
                    "text": rec.text,
                    "score": float(score),
                    "metadata": rec.metadata,
                    "modality": rec.modality,
                    "indexed_at": rec.indexed_at,
                }
            )

        return results[:top_k]

    # ── 统计 ────────────────────────────────────────────
    @property
    def count(self) -> int:
        return len(self._records)

    def stats(self) -> dict[str, Any]:
        return {
            "total_vectors": len(self._records),
            "dimension": self.dim,
            "index_path": str(self.index_path),
            "modalities": {
                m: sum(1 for r in self._records if r.modality == m)
                for m in set(r.modality for r in self._records)
            },
        }


# ── 全局单例 ────────────────────────────────────────────
_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


def reset_vector_store():
    """重置向量存储（用于测试或重新索引）"""
    global _store
    if _store:
        _store._records.clear()
        _store._create_index()
        _store.save()
    _store = VectorStore()
    return _store
