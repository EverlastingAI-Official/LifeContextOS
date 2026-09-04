"""Fail when common secrets or local personal-data artifacts enter the public tree."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DATA_FILES = {ROOT / "data" / "README.md", ROOT / "RAWDATA" / "README.md"}
SKIP_DIRS = {".git", ".venv", ".runtime", "__pycache__", ".pytest_cache", ".ruff_cache"}
BINARY_SUFFIXES = {
    ".wav", ".pcm", ".mp3", ".m4a", ".flac", ".gguf", ".safetensors", ".pt", ".onnx",
}
TEXT_SUFFIXES = {
    "", ".md", ".txt", ".py", ".js", ".css", ".html", ".json", ".toml", ".yaml", ".yml",
    ".cmd", ".ps1", ".example",
}
PATTERNS = {
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "mainland China phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "mainland China ID": re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
}


def files() -> list[Path]:
    return [
        path for path in ROOT.rglob("*")
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts)
    ]


def main() -> int:
    findings: list[str] = []
    for path in files():
        relative = path.relative_to(ROOT)
        if path.suffix.lower() in BINARY_SUFFIXES:
            findings.append(f"forbidden binary: {relative}")
            continue
        if (ROOT / "data") in path.parents or (ROOT / "RAWDATA") in path.parents:
            if path not in ALLOWED_DATA_FILES:
                findings.append(f"personal-data directory entry: {relative}")
                continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {".gitignore", ".env.example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"non-UTF-8 text candidate: {relative}")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")

    if findings:
        print("Public-tree audit failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"Public-tree audit passed: {len(files())} files checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
