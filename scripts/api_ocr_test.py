"""Upload a PNG image to the API and verify PaddleOCR is used."""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8001"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "api_ocr_test.txt"
IMG = ROOT / "data" / "sample_ocr.png"

# Ensure a sample image exists
if not IMG.exists():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(img)
    lines = ["2026-01-15  记-008", "1002  银行存款", "收款  借方 5000"]
    y = 30
    for line in lines:
        draw.text((30, y), line, fill="black")
        y += 50
    img.save(IMG)


def log(msg: str) -> None:
    print(msg)


def req(method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    r = urllib.request.Request(BASE_URL + path, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    # Upload
    boundary = "----boundary123"
    payload = IMG.read_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test_ocr.png"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    log("Uploading image...")
    up = req("POST", "/api/files/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    log(f"upload: {json.dumps(up, ensure_ascii=False)}")
    tid = up["task_id"]

    # Run
    log("Running task...")
    req("POST", f"/api/tasks/{tid}/run")

    # Poll
    for _ in range(120):
        time.sleep(1)
        t = req("GET", f"/api/tasks/{tid}")
        log(f"  task: {t['status']} {t['progress']}% {t['current_step']}")
        if t["status"] in ("completed", "failed"):
            break

    if t["status"] != "completed":
        log(f"FAILED: {t}")
        return 1

    # Check if OCR found real text (not placeholder)
    records = req("GET", "/api/records?" + urllib.parse.urlencode({"page_size": 5}))
    log(f"records: {records['total']} items")
    for r in records["items"][:3]:
        log(f"  [{r['id']}] {r['summary'][:100]}")
        if "占位" in r["summary"] or "placeholder" in r["summary"].lower():
            log("  ^^ STILL USING PLACEHOLDER - PaddleOCR not invoked!")
            return 2

    log("SUCCESS: PaddleOCR was used via API!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
