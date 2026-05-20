from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples_ledger.csv"


def request(method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
    req = urllib.request.Request(BASE_URL + path, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = resp.read()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return json.loads(payload.decode("utf-8"))
        return payload


def upload_sample() -> dict:
    boundary = "----audit-platform-smoke-boundary"
    content = SAMPLE.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="samples_ledger.csv"\r\n',
            b"Content-Type: text/csv\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return request("POST", "/api/files/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def main() -> int:
    try:
        health = request("GET", "/api/health")
        print("health:", health)

        uploaded = upload_sample()
        print("upload:", uploaded)
        task_id = uploaded["task_id"]

        started = request("POST", f"/api/tasks/{task_id}/run")
        print("run:", started)

        task = {}
        for _ in range(30):
            time.sleep(1)
            task = request("GET", f"/api/tasks/{task_id}")
            print("task:", task["status"], task["progress"], task["current_step"])
            if task["status"] in {"completed", "failed"}:
                break

        if task.get("status") != "completed":
            raise RuntimeError(f"task did not complete: {task}")

        query = urllib.parse.urlencode({"voucher_no": "记-001", "page_size": 10})
        records = request("GET", f"/api/records?{query}")
        print("records:", records["total"])
        if records["total"] < 2:
            raise RuntimeError("expected at least two records for voucher 记-001")

        reports = request("GET", f"/api/reports/{task_id}")
        print("reports:", len(reports["reports"]), "exceptions:", len(reports["exceptions"]))

        xbrl = request("GET", f"/api/export/{task_id}?format=xbrl")
        if b"AuditLedger" not in xbrl:
            raise RuntimeError("xbrl export missing AuditLedger root")
        print("export: xbrl ok")
        print("smoke regression passed")
        return 0
    except urllib.error.URLError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"regression failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

