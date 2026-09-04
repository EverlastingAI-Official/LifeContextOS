"""Start, stop and inspect local model runtimes owned by LifeContext."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx


class RuntimeErrorDetail(RuntimeError):
    pass


class RuntimeManager:
    def __init__(self, project_root: Path, data_dir: Path) -> None:
        self.project_root = project_root
        self.data_dir = data_dir
        self.log_dir = data_dir / "runtime_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.llama_server = project_root / ".runtime" / "llama.cpp" / "llama-server.exe"
        self.llm_model = project_root / "models" / "qwen3-4b" / "Qwen3-4B-Q4_K_M.gguf"
        self.cosy_python = project_root / ".runtime" / "cosyvoice-venv" / "Scripts" / "python.exe"
        self.cosy_wrapper = project_root / "scripts" / "cosyvoice_cpu_server.py"
        self.cosy_model = self._find_cosy_model()
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._logs: list[Any] = []
        self._lock = threading.RLock()

    def _find_cosy_model(self) -> Path:
        root = self.project_root / ".runtime" / "modelscope-cache" / "FunAudioLLM"
        if root.exists():
            matches = sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("Fun-CosyVoice3"))
            if matches:
                return matches[0]
        return root / "Fun-CosyVoice3-0___5B-2512"

    @staticmethod
    def _port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            return False

    def _owned_process(self, service: str) -> subprocess.Popen[Any] | None:
        process = self._processes.get(service)
        if process is not None and process.poll() is not None:
            self._processes.pop(service, None)
            return None
        return process

    def _spawn(self, service: str, command: list[str], env: dict[str, str] | None = None) -> subprocess.Popen[Any]:
        output = (self.log_dir / f"{service}.log").open("ab")
        error = (self.log_dir / f"{service}.err.log").open("ab")
        self._logs.extend([output, error])
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(
            command,
            cwd=self.project_root,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=error,
            env=env,
            creationflags=flags,
            close_fds=True,
        )
        self._processes[service] = process
        return process

    def start(self, service: str) -> dict[str, Any]:
        with self._lock:
            if service == "llm":
                return self._start_llm()
            if service == "cosyvoice":
                return self._start_cosyvoice()
            raise RuntimeErrorDetail(f"Unknown runtime: {service}")

    def _start_llm(self) -> dict[str, Any]:
        if self._port_open(8080):
            return self.service_status("llm")
        missing = [str(path) for path in (self.llama_server, self.llm_model) if not path.exists()]
        if missing:
            raise RuntimeErrorDetail("Missing local LLM files: " + ", ".join(missing))
        process = self._spawn(
            "llm",
            [
                str(self.llama_server), "-m", str(self.llm_model),
                "--host", "127.0.0.1", "--port", "8080",
                "--device", "none", "--gpu-layers", "0", "--no-kv-offload", "--no-op-offload", "--fit", "off",
                "-c", "8192", "-np", "1", "--cache-ram", "0", "--jinja", "--no-webui",
            ],
        )
        return {"service": "llm", "state": "starting", "pid": process.pid, "mode": "cpu", "endpoint": "http://127.0.0.1:8080"}

    def _start_cosyvoice(self) -> dict[str, Any]:
        if self._port_open(50000):
            return self.service_status("cosyvoice")
        required = [
            self.cosy_python, self.cosy_wrapper, self.cosy_model / "cosyvoice3.yaml",
            self.cosy_model / "llm.pt", self.cosy_model / "flow.pt", self.cosy_model / "hift.pt",
            self.cosy_model / "speech_tokenizer_v3.onnx",
            self.cosy_model / "CosyVoice-BlankEN" / "model.safetensors",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise RuntimeErrorDetail("CosyVoice model is incomplete: " + ", ".join(missing))
        env = os.environ.copy()
        env.pop("CUDA_VISIBLE_DEVICES", None)
        env["COSYVOICE_DEVICE"] = "auto"
        env.setdefault("WINDIR", env.get("SystemRoot", r"C:\Windows"))
        cache_root = self.project_root / ".runtime" / "cosyvoice-cache"
        (cache_root / "huggingface").mkdir(parents=True, exist_ok=True)
        (cache_root / "matplotlib").mkdir(parents=True, exist_ok=True)
        env["HF_HOME"] = str(cache_root / "huggingface")
        env["MPLCONFIGDIR"] = str(cache_root / "matplotlib")
        process = self._spawn(
            "cosyvoice",
            [str(self.cosy_python), str(self.cosy_wrapper), "--model-dir", str(self.cosy_model), "--port", "50000"],
            env=env,
        )
        return {"service": "cosyvoice", "state": "loading", "pid": process.pid, "mode": "cuda_stream", "endpoint": "http://127.0.0.1:50000"}

    def stop(self, service: str) -> dict[str, Any]:
        with self._lock:
            if service not in {"llm", "cosyvoice"}:
                raise RuntimeErrorDetail(f"Unknown runtime: {service}")
            process = self._owned_process(service)
            if process is None:
                if self._port_open(8080 if service == "llm" else 50000):
                    raise RuntimeErrorDetail("Service is running outside this LifeContext session and cannot be stopped safely.")
                return self.service_status(service)
            process.terminate()
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            self._processes.pop(service, None)
            time.sleep(0.15)
            return self.service_status(service)

    def service_status(self, service: str) -> dict[str, Any]:
        if service not in {"llm", "cosyvoice"}:
            raise RuntimeErrorDetail(f"Unknown runtime: {service}")
        port = 8080 if service == "llm" else 50000
        process = self._owned_process(service)
        base: dict[str, Any] = {
            "service": service,
            "state": "stopped",
            "pid": process.pid if process else None,
            "owned": process is not None,
            "mode": "cpu" if service == "llm" else "cuda_stream",
            "endpoint": f"http://127.0.0.1:{port}",
        }
        if not self._port_open(port):
            if process is not None:
                base["state"] = "loading" if service == "cosyvoice" else "starting"
            return base
        base["state"] = "running"
        if service == "llm":
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
                health = response.json()
                base["health"] = health.get("status")
                if response.status_code != 200 or health.get("status") != "ok":
                    base["state"] = "loading"
            except (httpx.HTTPError, ValueError):
                base["health"] = "reachable"
        if service == "cosyvoice":
            try:
                health = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).json()
                base.update(health)
                if health.get("status") == "loading":
                    base["state"] = "loading"
                elif health.get("status") == "error":
                    base["state"] = "error"
                elif health.get("status") == "ready":
                    base["state"] = "running"
            except (httpx.HTTPError, ValueError):
                pass
        return base

    def status(self) -> dict[str, Any]:
        return {
            "llm": self.service_status("llm"),
            "cosyvoice": self.service_status("cosyvoice"),
        }

    def shutdown(self) -> None:
        for service in list(self._processes):
            try:
                self.stop(service)
            except RuntimeError:
                pass
