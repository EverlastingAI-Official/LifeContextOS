"""Command-line entry point for running LifeContext from a source checkout."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="lifecontext", description="LifeContext local API and UI")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run the API and UI in the foreground")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8787, help="Listen port (default: 8787)")
    serve.add_argument("--reload", action="store_true", help="Reload when backend source changes")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    os.chdir(root)
    env_file = root / ".env"
    print(f"LifeContext UI: http://{args.host}:{args.port}/ui/", flush=True)
    uvicorn.run(
        "lifecontext_api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(root / "apps" / "api")] if args.reload else None,
        env_file=str(env_file) if env_file.is_file() else None,
    )
