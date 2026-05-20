from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class FileUpload(Base):
    __tablename__ = "file_uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="uploaded", nullable=False)

    tasks: Mapped[list["TaskJob"]] = relationship(back_populates="file")


class TaskJob(Base):
    __tablename__ = "task_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("file_uploads.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    current_step: Mapped[str] = mapped_column(String(120), default="待处理", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[str] = mapped_column(Text, default="", nullable=False)

    file: Mapped[FileUpload] = relationship(back_populates="tasks")
    ocr_results: Mapped[list["OcrResult"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    records: Mapped[list["LedgerRecord"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    reports: Mapped[list["AuditReport"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class OcrResult(Base):
    __tablename__ = "ocr_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_jobs.id"), nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_fields: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.9, nullable=False)
    source_bbox: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    task: Mapped[TaskJob] = relationship(back_populates="ocr_results")


class LedgerRecord(Base):
    __tablename__ = "ledger_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_jobs.id"), nullable=False, index=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("file_uploads.id"), nullable=False, index=True)
    record_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, index=True)
    voucher_no: Mapped[str] = mapped_column(String(80), default="", index=True)
    account_code: Mapped[str] = mapped_column(String(80), default="", index=True)
    account_name: Mapped[str] = mapped_column(String(160), default="", index=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    debit: Mapped[float] = mapped_column(Float, default=0.0)
    credit: Mapped[float] = mapped_column(Float, default=0.0)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    source_page: Mapped[int] = mapped_column(Integer, default=1)
    source_row: Mapped[int] = mapped_column(Integer, default=0)
    source_text: Mapped[str] = mapped_column(Text, default="")
    is_exception: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exception_reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    task: Mapped[TaskJob] = relationship(back_populates="records")


class AuditReport(Base):
    __tablename__ = "audit_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_jobs.id"), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    task: Mapped[TaskJob] = relationship(back_populates="reports")


class AccountMapping(Base):
    __tablename__ = "account_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    raw_account: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    standard_code: Mapped[str] = mapped_column(String(80), nullable=False)
    standard_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule: Mapped[str] = mapped_column(String(300), default="精确匹配")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
