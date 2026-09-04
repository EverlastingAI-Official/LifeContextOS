"""Download the latest official llama.cpp Windows CUDA 12 runtime."""

from __future__ import annotations

import json
import shutil
import urllib.request
import urllib.error
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "llama.cpp"
CACHE = ROOT / ".runtime" / "downloads"
API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
PINNED_TAG = "b9631"


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "LifeContext-L1/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output, length=4 * 1024 * 1024)


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    if (RUNTIME / "llama-server.exe").exists():
        print(f"LLAMA_RUNTIME_READY={RUNTIME}")
        return
    request = urllib.request.Request(API, headers={"User-Agent": "LifeContext-L1/0.1", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
        assets = release.get("assets", [])
        wanted = []
        for asset in assets:
            name = asset["name"].lower()
            if ("bin-win-cuda-12.4-x64.zip" in name and name.startswith("llama-")) or name == "cudart-llama-bin-win-cuda-12.4-x64.zip":
                wanted.append(asset)
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        names = [f"llama-{PINNED_TAG}-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]
        wanted = [{"name": name, "browser_download_url": f"https://github.com/ggml-org/llama.cpp/releases/download/{PINNED_TAG}/{name}"} for name in names]
    if not wanted:
        raise RuntimeError("No compatible Windows CUDA 12 llama.cpp assets were found")
    for asset in wanted:
        archive = CACHE / asset["name"]
        print(f"Downloading {asset['name']}", flush=True)
        download(asset["browser_download_url"], archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(RUNTIME)
    if not (RUNTIME / "llama-server.exe").exists():
        matches = list(RUNTIME.rglob("llama-server.exe"))
        if matches:
            for item in matches[0].parent.iterdir():
                if item.is_file():
                    shutil.copy2(item, RUNTIME / item.name)
    if not (RUNTIME / "llama-server.exe").exists():
        raise RuntimeError("llama-server.exe was not found after extraction")
    print(f"LLAMA_RUNTIME_READY={RUNTIME}", flush=True)


if __name__ == "__main__":
    main()
