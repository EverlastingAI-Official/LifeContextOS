"""Launch the resumable model downloader as a detached Windows process."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / ".runtime" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
downloader = ROOT / "scripts" / "download_local_model.py"
with (LOG_DIR / "qwen-download.log").open("ab") as output, (LOG_DIR / "qwen-download.err.log").open("ab") as error:
    process = subprocess.Popen(
        [sys.executable, str(downloader)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=output,
        stderr=error,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
print(f"DOWNLOAD_STARTED PID={process.pid}")
