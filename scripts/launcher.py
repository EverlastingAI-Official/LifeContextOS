"""One-click local launcher for the API and HARNESS UI.

Model runtimes are intentionally started from the UI runtime center.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / ".runtime" / "logs"
FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


def detached(command: list[str], stdout_name: str, stderr_name: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout = (LOG_DIR / stdout_name).open("ab")
    stderr = (LOG_DIR / stderr_name).open("ab")
    subprocess.Popen(
        command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        creationflags=FLAGS, close_fds=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not PYTHON.exists():
        raise SystemExit(f"Missing API environment: {PYTHON}")
    if not port_open(8787):
        detached([
            str(PYTHON), "-m", "uvicorn", "lifecontext_api.main:app",
            "--host", "127.0.0.1", "--port", "8787",
        ], "api.log", "api.err.log")
        for _ in range(30):
            if port_open(8787):
                break
            time.sleep(0.2)
    if not port_open(8787):
        raise SystemExit(f"LifeContext API did not start. See {LOG_DIR / 'api.err.log'}")
    if not args.no_browser:
        webbrowser.open("http://127.0.0.1:8787/ui/")
    print("LifeContext is ready at http://127.0.0.1:8787/ui/")


if __name__ == "__main__":
    main()
