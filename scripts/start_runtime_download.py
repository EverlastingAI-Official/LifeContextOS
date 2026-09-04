from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / ".runtime" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
with (LOG_DIR / "llama-download.log").open("ab") as output, (LOG_DIR / "llama-download.err.log").open("ab") as error:
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "download_llama_runtime.py")],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=error,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
print(f"RUNTIME_DOWNLOAD_STARTED PID={process.pid}")
