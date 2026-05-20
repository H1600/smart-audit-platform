"""Standalone OCR test that directly uses PaddleOCR without the web API."""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# Register torch DLL path before any imports
try:
    import importlib.util
    spec = importlib.util.find_spec("torch")
    if spec and spec.submodule_search_locations:
        lib_dir = Path(spec.submodule_search_locations[0]) / "lib"
        if lib_dir.exists():
            os.add_dll_directory(str(lib_dir))
            os.environ["PATH"] = f"{lib_dir}{os.pathsep}{os.environ.get('PATH', '')}"
except Exception:
    pass

# Paddle flags
for flag in ("FLAGS_use_mkldnn", "FLAGS_enable_mkldnn", "FLAGS_use_onednn",
             "FLAGS_enable_onednn", "FLAGS_enable_pir_api",
             "FLAGS_enable_pir_infer", "FLAGS_use_pir_api"):
    os.environ[flag] = "0"

OUT = Path(__file__).resolve().parent.parent / "data" / "ocr_standalone.txt"


def log(msg: str) -> None:
    print(msg)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def main() -> int:
    log("=== standalone OCR test ===")
    log(f"python: {sys.version}")

    # 1. check imports
    log("--- imports ---")
    for name in ("torch", "paddle", "paddleocr"):
        try:
            __import__(name)
            log(f"  {name}: ok")
        except Exception as exc:
            log(f"  {name}: FAIL {exc}")

    # 2. init PaddleOCR
    log("--- init PaddleOCR ---")
    try:
        from paddleocr import PaddleOCR
        ocr = PaddleOCR(use_textline_orientation=True, lang="ch", show_log=False)
        log("  PaddleOCR init OK")
    except Exception as exc:
        log(f"  PaddleOCR init FAIL: {exc}")
        traceback.print_exc(file=open(OUT.with_suffix(".err"), "w"))
        return 1

    # 3. create a sample image with text
    log("--- create sample image ---")
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (800, 200), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
        lines = [
            "日期 2026-01-15  凭证号 记-008",
            "科目编码 1002  科目名称 银行存款",
            "摘要 收款 借方 5000  贷方 0  余额 15000",
        ]
        y = 30
        for line in lines:
            draw.text((30, y), line, fill="black", font=font)
            y += 50
        tmp = Path(tempfile.mktemp(suffix=".png"))
        img.save(tmp)
        log(f"  image saved: {tmp}")
    except Exception as exc:
        log(f"  image create FAIL: {exc}")
        return 1

    # 4. run OCR
    log("--- run OCR ---")
    try:
        result = ocr.ocr(str(tmp))
        items = []
        if result:
            page = result[0] if isinstance(result, list) and len(result) > 0 else result
            if isinstance(page, list):
                for item in page:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        text = str(item[1][0]) if isinstance(item[1], (list, tuple)) else str(item[1])
                        score = float(item[1][1]) if isinstance(item[1], (list, tuple)) and len(item[1]) > 1 else 0.0
                        items.append({"text": text, "score": score})
        if items:
            log(f"  ocr found {len(items)} text items:")
            for it in items:
                log(f"    [{it['score']:.3f}] {it['text']}")
        else:
            log("  ocr found NO text items (empty result)")
    except Exception as exc:
        log(f"  OCR run FAIL: {exc}")
        traceback.print_exc(file=open(OUT.with_suffix(".err"), "w"))
        return 1
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass

    log("=== standalone OCR test PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
