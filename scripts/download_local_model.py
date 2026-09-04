"""Resumable download of the official Qwen3-4B Q4_K_M GGUF model."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "models" / "qwen3-4b"
TARGET = MODEL_DIR / "Qwen3-4B-Q4_K_M.gguf"
PARTIAL = TARGET.with_suffix(".gguf.partial")
STATUS = MODEL_DIR / "download-status.json"
URL = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf?download=true"


def save_status(**values: object) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    values["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATUS)


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        save_status(status="complete", downloaded=TARGET.stat().st_size, total=TARGET.stat().st_size, progress=100)
        print(f"MODEL_DOWNLOAD_COMPLETE={TARGET}", flush=True)
        return
    downloaded = PARTIAL.stat().st_size if PARTIAL.exists() else 0
    request = urllib.request.Request(URL, headers={"User-Agent": "LifeContext-L1/0.1"})
    if downloaded:
        request.add_header("Range", f"bytes={downloaded}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        content_length = int(response.headers.get("Content-Length", "0"))
        ranged = response.status == 206
        if downloaded and not ranged:
            downloaded = 0
        total = downloaded + content_length if ranged else content_length
        mode = "ab" if ranged else "wb"
        started = time.monotonic()
        checkpoint = time.monotonic()
        with PARTIAL.open(mode) as output:
            while True:
                block = response.read(4 * 1024 * 1024)
                if not block:
                    break
                output.write(block)
                downloaded += len(block)
                now = time.monotonic()
                if now - checkpoint >= 2:
                    elapsed = max(0.1, now - started)
                    progress = round(downloaded * 100 / total, 2) if total else 0
                    save_status(status="downloading", downloaded=downloaded, total=total, progress=progress, bytes_per_second=round(downloaded / elapsed))
                    print(f"{progress:.2f}% {downloaded}/{total}", flush=True)
                    checkpoint = now
    PARTIAL.replace(TARGET)
    save_status(status="complete", downloaded=downloaded, total=downloaded, progress=100)
    print(f"MODEL_DOWNLOAD_COMPLETE={TARGET}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        save_status(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
