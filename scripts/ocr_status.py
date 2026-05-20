from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ocr_status.json"


def main() -> int:
    try:
        with urllib.request.urlopen(BASE_URL + "/api/ocr/check", timeout=30) as resp:
            payload = resp.read().decode("utf-8")
        OUT.write_text(payload, encoding="utf-8")
        print("wrote", OUT)
        return 0
    except Exception as exc:
        OUT.write_text(json.dumps({"error": str(exc)}), encoding="utf-8")
        print("failed", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
