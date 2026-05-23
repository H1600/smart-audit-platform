"""索引器 —— 文档/图像 → 分块 → 嵌入 → 向量库

支持:
- 文本文档索引（Excel 行 / PDF 页 / OCR 结果）
- 发票图像索引（OCR 文本 + 图像嵌入融合）
- 批量索引任务
- 增量更新
- 索引状态查询
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from ..models import FileUpload, LedgerRecord, OcrResult, TaskJob
from .embeddings import chunk_text, embed_chunks, embed_ocr_image, embed_text
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)


def index_ledger_records(
    db: Session,
    task_id: int | None = None,
    batch_size: int = 100,
    force: bool = False,
) -> dict[str, Any]:
    """将 LedgerRecord 索引到向量库"""
    store = get_vector_store()

    query = db.query(LedgerRecord)
    if task_id is not None:
        query = query.filter(LedgerRecord.task_id == task_id)

    total = query.count()
    if total == 0:
        return {"indexed": 0, "total": 0, "status": "empty"}

    # 检查已索引（简单策略：有 task_id 则先删后重建）
    if task_id is not None and force:
        existing_ids = [r.id for r in store._records if r.metadata.get("task_id") == task_id]
        if existing_ids:
            store.remove(existing_ids)

    indexed = 0
    offset = 0
    skipped = 0

    while offset < total:
        records = query.offset(offset).limit(batch_size).all()
        texts = []
        metadatas = []
        ids = []

        for rec in records:
            # 构建索引文本：科目编码 + 科目名称 + 摘要 + 金额
            idx_text = (
                f"凭证号:{rec.voucher_no} "
                f"科目:{rec.account_code} {rec.account_name} "
                f"摘要:{rec.summary} "
                f"借方:{rec.debit:.2f} 贷方:{rec.credit:.2f} "
                f"日期:{rec.record_date}"
            )
            texts.append(idx_text)
            metadatas.append(
                {
                    "record_id": rec.id,
                    "task_id": rec.task_id,
                    "file_id": rec.file_id,
                    "account_code": rec.account_code,
                    "account_name": rec.account_name,
                    "voucher_no": rec.voucher_no,
                    "is_exception": rec.is_exception,
                    "record_date": str(rec.record_date) if rec.record_date else "",
                    "type": "ledger_record",
                }
            )
            ids.append(f"lr_{rec.id}")

        if texts:
            vectors = embed_text(texts)
            store.add(vectors, texts=texts, metadatas=metadatas, ids=ids, modality="text")
            indexed += len(texts)

        offset += batch_size

    return {"indexed": indexed, "total": total, "skipped": skipped, "status": "completed"}


def index_ocr_results(
    db: Session,
    task_id: int | None = None,
    include_images: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """将 OCR 结果索引到向量库（文本 + 可选的图像嵌入）"""
    store = get_vector_store()

    query = db.query(OcrResult)
    if task_id is not None:
        query = query.filter(OcrResult.task_id == task_id)
    if force and task_id is not None:
        existing_ids = [r.id for r in store._records if r.metadata.get("task_id") == task_id]
        if existing_ids:
            store.remove(existing_ids)

    results = query.all()
    indexed_text = 0
    indexed_image = 0

    for ocr in results:
        # 文本索引
        if ocr.raw_text:
            chunks = chunk_text(ocr.raw_text)
            if chunks:
                vectors = embed_text(chunks)
                store.add(
                    vectors,
                    texts=chunks,
                    metadatas=[
                        {
                            "ocr_id": ocr.id,
                            "task_id": ocr.task_id,
                            "page_no": ocr.page_no,
                            "chunk_index": i,
                            "type": "ocr_text",
                        }
                        for i in range(len(chunks))
                    ],
                    ids=[f"ocr_txt_{ocr.id}_{i}" for i in range(len(chunks))],
                    modality="text",
                )
                indexed_text += len(chunks)

        # 图像索引（如果有图像文件）
        if include_images:
            task = db.get(TaskJob, ocr.task_id)
            if task and task.file:
                storage_path = Path(task.file.storage_path)
                if storage_path.exists() and storage_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
                    fused_vec = embed_ocr_image(storage_path, ocr.raw_text)
                    store.add(
                        fused_vec.reshape(1, -1),
                        texts=[ocr.raw_text[:500]],
                        metadatas=[{"ocr_id": ocr.id, "task_id": ocr.task_id, "page_no": ocr.page_no, "type": "ocr_image"}],
                        ids=[f"ocr_img_{ocr.id}"],
                        modality="fused",
                    )
                    indexed_image += 1

    return {
        "indexed_text_chunks": indexed_text,
        "indexed_images": indexed_image,
        "total_ocr": len(results),
        "status": "completed",
    }


def index_invoice_fields(
    db: Session,
    task_id: int,
    invoices: list[dict[str, Any]],
    image_paths: list[str] | None = None,
) -> dict[str, Any]:
    """索引发票结构化字段（文本+图像融合）"""
    store = get_vector_store()
    indexed = 0

    for i, inv in enumerate(invoices):
        # 构建发票索引文本
        idx_text = (
            f"发票代码:{inv.get('invoice_code', '')} "
            f"发票号码:{inv.get('invoice_no', '')} "
            f"日期:{inv.get('invoice_date', '')} "
            f"销售方:{inv.get('seller_name', '')} "
            f"购买方:{inv.get('buyer_name', '')} "
            f"金额:{inv.get('total_amount', 0):.2f} "
            f"税额:{inv.get('total_tax', 0):.2f} "
            f"价税合计:{inv.get('grand_total', 0):.2f}"
        )

        # 如果有对应图像，做融合嵌入
        if image_paths and i < len(image_paths) and Path(image_paths[i]).exists():
            fused_vec = embed_ocr_image(image_paths[i], idx_text)
            modality = "fused"
        else:
            fused_vec = embed_text(idx_text)
            modality = "text"

        store.add(
            fused_vec.reshape(1, -1),
            texts=[idx_text],
            metadatas=[
                {
                    "task_id": task_id,
                    "invoice_index": i,
                    "invoice_no": inv.get("invoice_no", ""),
                    "seller_name": inv.get("seller_name", ""),
                    "type": "invoice",
                }
            ],
            ids=[f"inv_{task_id}_{i}"],
            modality=modality,
        )
        indexed += 1

    return {"indexed_invoices": indexed, "status": "completed"}


def index_status() -> dict[str, Any]:
    """查询索引状态"""
    store = get_vector_store()
    return {
        "store": store.stats(),
        "last_updated": datetime.utcnow().isoformat(),
    }


def reindex_all(db: Session) -> dict[str, Any]:
    """全量重建索引（清空后重新索引所有记录）"""
    from .vector_store import reset_vector_store

    logger.info("开始全量重建索引...")
    reset_vector_store()

    result = {
        "ledger": index_ledger_records(db, force=True),
        "ocr": index_ocr_results(db, force=True),
    }

    return {"status": "completed", "details": result}
