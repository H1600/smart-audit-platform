from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .settings import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_indexes() -> None:
    """Create performance indexes if they don't exist."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_ledger_record_date ON ledger_records(record_date)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_voucher_no ON ledger_records(voucher_no)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_account_code ON ledger_records(account_code)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_account_name ON ledger_records(account_name)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_is_exception ON ledger_records(is_exception)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_task_date ON ledger_records(task_id, record_date)",
        "CREATE INDEX IF NOT EXISTS idx_ledger_task_code ON ledger_records(task_id, account_code)",
        "CREATE INDEX IF NOT EXISTS idx_ocr_task_id ON ocr_results(task_id)",
        "CREATE INDEX IF NOT EXISTS idx_report_task_id ON audit_reports(task_id)",
        "CREATE INDEX IF NOT EXISTS idx_task_status ON task_jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_file_status ON file_uploads(status)",
    ]
    with engine.connect() as conn:
        for idx_sql in indexes:
            try:
                conn.execute(text(idx_sql))
            except Exception:
                pass
        conn.commit()

