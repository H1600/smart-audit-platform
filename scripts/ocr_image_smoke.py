from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sample_ocr.png"
LOG = ROOT / "data" / "ocr_smoke.txt"
REQUEST_TIMEOUT = 90
MAX_WAIT = 120


def request(method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
    req = urllib.request.Request(BASE_URL + path, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        payload = resp.read()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return json.loads(payload.decode("utf-8"))
        return payload


def build_image(path: Path) -> None:
    img = Image.new("RGB", (1100, 260), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    lines = [
        "Date 2026-01-03  Voucher V-003",
        "Account 1002  BankDeposit",
        "Summary Receive  Credit 0  Debit 500  Balance 1500",
    ]
    y = 30
    for line in lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 50
    img.save(path)


def upload_image(path: Path) -> dict:
    boundary = "----audit-platform-ocr-boundary"
    content = path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="sample_ocr.png"\r\n',
            b"Content-Type: image/png\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return request("POST", "/api/files/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def main() -> int:
    try:
        def log(msg: str) -> None:
            LOG.write_text(f"{msg}\n", encoding="utf-8", errors="ignore") if not LOG.exists() else LOG.write_text(LOG.read_text(encoding="utf-8", errors="ignore") + f"{msg}\n", encoding="utf-8", errors="ignore")
            print(msg)

        log(f"health: {request('GET', '/api/health')}")
        build_image(OUT)
        upload = upload_image(OUT)
        log(f"upload: {upload}")
        task_id = upload["task_id"]

        request("POST", f"/api/tasks/{task_id}/run")
        task = {}
        for _ in range(MAX_WAIT):
            time.sleep(1)
            task = request("GET", f"/api/tasks/{task_id}")
            log(f"task: {task['status']} {task['progress']} {task['current_step']}")
            if task["status"] in {"completed", "failed"}:
                break

        if task.get("status") != "completed":
            raise RuntimeError(f"task did not complete: {task}")

        records = request("GET", "/api/records?" + urllib.parse.urlencode({"page_size": 5}))
        log(f"records: {records['total']} {records['items'][:2]}")
        log("ocr image smoke passed")
        return 0
    except urllib.error.URLError as exc:
        LOG.write_text(f"request failed: {exc}\n", encoding="utf-8", errors="ignore")
        print(f"request failed: {exc}", file=sys.stderr)
    except Exception as exc:
        LOG.write_text(f"ocr image regression failed: {exc}\n", encoding="utf-8", errors="ignore")
        print(f"ocr image regression failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
