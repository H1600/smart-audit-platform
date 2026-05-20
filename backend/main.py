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

from .database import Base, SessionLocal, engine, get_db
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


logging.basicConfig(
    filename=LOG_DIR / "app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


Base.metadata.create_all(bind=engine)
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
def export(task_id: int, format: str = Query("excel", pattern="^(excel|xbrl|report)$"), db: Session = Depends(get_db)):
    task = db.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    path = export_task(db, task_id, format)
    return FileResponse(path, filename=Path(path).name)


frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
