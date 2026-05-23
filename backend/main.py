from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, ensure_indexes, get_db
from .models import AuditReport, LedgerRecord, TaskJob
from .services import (
    export_task,
    init_db_seed,
    ocr_diagnostics,
    process_task,
    query_records,
    record_to_dict,
    report_to_dict,
    save_upload,
    task_to_dict,
)
from .settings import BASE_DIR, LOG_DIR
from .account_classifier import (
    classifier_exists,
    get_keyword_map,
    get_model_meta,
    predict_account_with_code,
    train_classifier,
)
from .analysis import (
    account_distribution,
    amount_distribution,
    exception_distribution,
    full_analysis,
    monthly_trend,
    task_statistics,
)
from .sampling import (
    export_sampling_result,
    large_amount_sample,
    random_sample,
    stratified_sample,
)
from .reconciliation import (
    detect_bank_template,
    parse_bank_statement,
    reconcile,
)
from .merger import (
    budget_comparison,
    merge_tables,
)
from .invoice_ocr import (
    batch_extract_invoices,
    export_invoice_summary,
    extract_invoice_fields,
)
from .ai.serving import router as ai_router

logging.basicConfig(
    filename=LOG_DIR / "app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


Base.metadata.create_all(bind=engine)
ensure_indexes()
with SessionLocal() as seed_db:
    init_db_seed(seed_db)

app = FastAPI(title="智能财务审计数据处理平台", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "smart-audit-platform"}


@app.get("/api/ocr/check")
def ocr_check():
    return ocr_diagnostics()


@app.post("/api/files/upload")
def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        file_row, task = save_upload(file, db)
        return {"file_id": file_row.id, "task_id": task.id, "filename": file_row.filename, "status": task.status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/run")
def run_task(task_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    task = db.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status == "running":
        return task_to_dict(task)
    background_tasks.add_task(process_task, task_id, SessionLocal)
    return {"task_id": task_id, "status": "queued", "message": "处理任务已启动"}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_to_dict(task)


@app.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.scalars(select(TaskJob).order_by(TaskJob.id.desc()).limit(20)).all()
    return [task_to_dict(task) for task in tasks]


@app.get("/api/records")
def records(
    start_date: date | None = None,
    end_date: date | None = None,
    account: str | None = None,
    voucher_no: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return query_records(db, start_date, end_date, account, voucher_no, min_amount, max_amount, page, page_size)


@app.get("/api/records/{record_id}")
def record_detail(record_id: int, db: Session = Depends(get_db)):
    record = db.get(LedgerRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record_to_dict(record)


@app.get("/api/reports/{task_id}")
def reports(task_id: int, db: Session = Depends(get_db)):
    task = db.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    report_rows = db.scalars(select(AuditReport).where(AuditReport.task_id == task_id).order_by(AuditReport.id)).all()
    exception_rows = db.scalars(select(LedgerRecord).where(LedgerRecord.task_id == task_id, LedgerRecord.is_exception == True)).all()
    return {
        "task": task_to_dict(task),
        "reports": [report_to_dict(row) for row in report_rows],
        "exceptions": [record_to_dict(row) for row in exception_rows],
    }


@app.get("/api/export/{task_id}")
def export(task_id: int, format: str = Query("excel", pattern="^(excel|xbrl|report|docx)$"), db: Session = Depends(get_db)):
    task = db.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    path = export_task(db, task_id, format)
    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xml": "application/xml",
        "json": "application/json",
        "csv": "text/csv",
    }
    ext = path.suffix.lower()
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(path, filename=path.name, media_type=media_type)


# ── Account Classifier (ML) ───────────────────────────────────────
@app.get("/api/accounts/classifier/status")
def classifier_status():
    meta = get_model_meta()
    return {
        "exists": classifier_exists(),
        **meta,
        "keyword_map_size": len(get_keyword_map()),
    }


@app.post("/api/accounts/classifier/train")
def train_account_classifier(payload: dict, db: Session = Depends(get_db)):
    """Train the ML classifier from uploaded (summary, account_name) pairs.

    Body: {"samples": [{"summary": "...", "account_name": "..."}, ...]}
    """
    samples = payload.get("samples", [])
    if not samples:
        # Auto-collect from existing records that have both summary and account_name
        from sqlalchemy import select as s

        rows = db.execute(
            s(LedgerRecord.summary, LedgerRecord.account_name)
            .where(LedgerRecord.summary != "", LedgerRecord.account_name != "", LedgerRecord.account_name != "未映射")
            .limit(2000)
        ).all()
        if not rows:
            raise HTTPException(status_code=400, detail="没有足够的训练数据，请先处理文件或手工提供样本")
        summaries = [r[0] for r in rows if r[0] and r[1]]
        labels = [r[1] for r in rows if r[0] and r[1]]
    else:
        summaries = [s["summary"] for s in samples if s.get("summary")]
        labels = [s["account_name"] for s in samples if s.get("account_name")]

    if len(summaries) < 5:
        raise HTTPException(status_code=400, detail=f"训练数据不足（需要至少5条，当前{len(summaries)}条）")

    meta = train_classifier(summaries, labels)
    return {"status": "trained", **meta}


@app.post("/api/accounts/classifier/predict")
def predict(payload: dict):
    """Predict account from summary text.

    Body: {"summary": "支付购口罩款"}
    """
    summary = payload.get("summary", "")
    if not summary:
        raise HTTPException(status_code=400, detail="请输入摘要文本")
    code, name, confidence = predict_account_with_code(summary)
    return {"summary": summary, "account_code": code, "account_name": name, "confidence": confidence}


@app.get("/api/accounts/mappings")
def list_mappings(db: Session = Depends(get_db)):
    from .models import AccountMapping

    rows = db.scalars(select(AccountMapping).order_by(AccountMapping.id)).all()
    return [
        {"id": r.id, "raw_account": r.raw_account, "standard_code": r.standard_code, "standard_name": r.standard_name, "rule": r.rule, "enabled": r.enabled}
        for r in rows
    ]


# ── Analysis / Dashboard ──────────────────────────────────────────
@app.get("/api/analysis/trend")
def analysis_trend(start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)):
    return monthly_trend(db, start_date, end_date)


@app.get("/api/analysis/accounts")
def analysis_accounts(db: Session = Depends(get_db)):
    return account_distribution(db)


@app.get("/api/analysis/exceptions")
def analysis_exceptions(db: Session = Depends(get_db)):
    return exception_distribution(db)


@app.get("/api/analysis/amounts")
def analysis_amounts(db: Session = Depends(get_db)):
    return amount_distribution(db)


@app.get("/api/analysis/tasks")
def analysis_tasks(db: Session = Depends(get_db)):
    return task_statistics(db)


@app.get("/api/analysis/full")
def analysis_full(db: Session = Depends(get_db)):
    return full_analysis(db)


# ── Sampling ──────────────────────────────────────────────────────
@app.get("/api/sampling/random")
def sampling_random(
    task_id: int | None = None,
    sample_size: int = Query(20, ge=1, le=500),
    start_date: date | None = None,
    end_date: date | None = None,
    account: str | None = None,
    is_exception: bool | None = None,
    db: Session = Depends(get_db),
):
    filters = {k: v for k, v in {"start_date": start_date, "end_date": end_date, "account": account, "is_exception": is_exception}.items() if v is not None}
    return random_sample(db, task_id, sample_size, **filters)


@app.get("/api/sampling/stratified")
def sampling_stratified(
    task_id: int | None = None,
    sample_size: int = Query(20, ge=1, le=500),
    stratify_by: str = Query("account_code"),
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    filters = {k: v for k, v in {"start_date": start_date, "end_date": end_date}.items() if v is not None}
    return stratified_sample(db, task_id, sample_size, stratify_by, **filters)


@app.get("/api/sampling/large")
def sampling_large(
    task_id: int | None = None,
    threshold: float = Query(10000.0, ge=0),
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    filters = {k: v for k, v in {"start_date": start_date, "end_date": end_date}.items() if v is not None}
    return large_amount_sample(db, task_id, threshold, **filters)


@app.get("/api/sampling/export")
def sampling_export(
    task_id: int | None = None,
    method: str = Query("random", pattern="^(random|stratified|large)$"),
    sample_size: int = Query(20, ge=1, le=500),
    threshold: float = Query(10000.0, ge=0),
    stratify_by: str = Query("account_code"),
    fmt: str = Query("excel", pattern="^(excel|csv)$"),
    db: Session = Depends(get_db),
):
    if method == "random":
        records = random_sample(db, task_id, sample_size)
    elif method == "stratified":
        records = stratified_sample(db, task_id, sample_size, stratify_by)
    else:
        records = large_amount_sample(db, task_id, threshold)
    path = export_sampling_result(records, fmt)
    return FileResponse(path, filename=Path(path).name)


# ── Bank Reconciliation ───────────────────────────────────────────
@app.post("/api/reconciliation/parse")
def parse_bank_file(file: UploadFile = File(...)):
    """Parse a bank statement file and return standardized records."""
    try:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xls"}:
            raise HTTPException(status_code=400, detail="仅支持 CSV/Excel 银行对账单")
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            import shutil
            shutil.copyfileobj(file.file, tmp)
            tmp_path = Path(tmp.name)
        records = parse_bank_statement(tmp_path)
        tmp_path.unlink(missing_ok=True)
        return {"records": records, "count": len(records)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/reconciliation/reconcile")
def do_reconcile(
    task_id: int = Query(...),
    bank_file: UploadFile = File(...),
    tolerance: float = Query(0.01, ge=0),
    db: Session = Depends(get_db),
):
    """Reconcile bank statement against task ledger records."""
    try:
        suffix = Path(bank_file.filename or "").suffix.lower()
        import tempfile, shutil
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            shutil.copyfileobj(bank_file.file, tmp)
            tmp_path = Path(tmp.name)
        bank_records = parse_bank_statement(tmp_path)
        tmp_path.unlink(missing_ok=True)

        ledger_records = list(db.scalars(select(LedgerRecord).where(LedgerRecord.task_id == task_id)))
        result = reconcile(bank_records, ledger_records, tolerance)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Multi-table Merge & Budget ────────────────────────────────────
@app.get("/api/merger/merge")
def merge(
    task_ids: str = Query("", description="Comma-separated task IDs"),
    merge_key: str = Query("account_code"),
    db: Session = Depends(get_db),
):
    ids = [int(x.strip()) for x in task_ids.split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="请提供至少2个任务ID（逗号分隔）")
    return merge_tables(db, ids, merge_key)


@app.get("/api/merger/budget")
def budget_compare(
    budget_task_id: int = Query(...),
    actual_task_id: int = Query(...),
    db: Session = Depends(get_db),
):
    return budget_comparison(db, budget_task_id, actual_task_id)


# ── Invoice OCR ───────────────────────────────────────────────────
@app.post("/api/invoice/extract")
def extract_invoice(payload: dict):
    """Extract invoice fields from OCR text.

    Body: {"text": "OCR raw text..."}
    """
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="请输入OCR文本")
    return extract_invoice_fields(text)


@app.post("/api/invoice/batch")
def batch_invoice(
    task_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Batch extract invoices from a task's OCR results."""
    from .models import OcrResult

    ocr_results = list(db.scalars(select(OcrResult).where(OcrResult.task_id == task_id)))
    if not ocr_results:
        raise HTTPException(status_code=404, detail="该任务没有OCR结果")

    items = [{"id": o.id, "raw_text": o.raw_text, "page_no": o.page_no} for o in ocr_results]
    invoices = batch_extract_invoices(items)
    return {"invoices": invoices, "count": len(invoices)}


@app.get("/api/invoice/export")
def export_invoices(
    task_id: int = Query(...),
    fmt: str = Query("excel", pattern="^(excel|csv)$"),
    db: Session = Depends(get_db),
):
    """Export extracted invoice data."""
    from .models import OcrResult

    ocr_results = list(db.scalars(select(OcrResult).where(OcrResult.task_id == task_id)))
    items = [{"id": o.id, "raw_text": o.raw_text, "page_no": o.page_no} for o in ocr_results]
    invoices = batch_extract_invoices(items)
    path = export_invoice_summary(invoices, fmt)
    return FileResponse(path, filename=Path(path).name)


app.include_router(ai_router)

frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
