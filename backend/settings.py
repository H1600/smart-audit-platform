import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"
LOG_DIR = BASE_DIR / "logs"
EXPORT_DIR = STORAGE_DIR / "exports"
UPLOAD_DIR = STORAGE_DIR / "uploads"

DATABASE_URL = f"sqlite:///{DATA_DIR / 'audit.db'}"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".xlsx", ".xls", ".csv"}
OCR_MODEL_DIR = Path(os.getenv("OCR_MODEL_DIR", "")).expanduser()
if not str(OCR_MODEL_DIR).strip():
    OCR_MODEL_DIR = None

OCR_ENGINE = os.getenv("OCR_ENGINE", "auto").strip().lower()
OCR_LANGS = [lang.strip() for lang in os.getenv("OCR_LANGS", "zh,en").split(",") if lang.strip()]
try:
    OCR_MIN_CONF = float(os.getenv("OCR_MIN_CONF", "0.55"))
except ValueError:
    OCR_MIN_CONF = 0.55
OCR_TEXTLINE = os.getenv("OCR_TEXTLINE", "1").strip().lower() not in {"0", "false", "no"}

for directory in (DATA_DIR, STORAGE_DIR, LOG_DIR, EXPORT_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

