from __future__ import annotations

import importlib.util
import os
import traceback
from pathlib import Path


def _ensure_torch_dlls() -> None:
    try:
        spec = importlib.util.find_spec("torch")
        if not spec or not spec.submodule_search_locations:
            return
        torch_dir = Path(spec.submodule_search_locations[0])
        lib_dir = torch_dir / "lib"
        if lib_dir.exists():
            os.add_dll_directory(str(lib_dir))
            os.environ["PATH"] = f"{lib_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    except Exception:
        pass


_ensure_torch_dlls()

from paddleocr import PaddleOCR

try:
    PaddleOCR(use_textline_orientation=True, lang="ch")
    print("init-ok")
except Exception as exc:
    print("init-fail", exc)
    traceback.print_exc()
