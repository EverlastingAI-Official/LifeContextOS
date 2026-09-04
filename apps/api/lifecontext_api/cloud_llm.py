"""OpenAI-compatible cloud inference adapter.

Only non-secret connection metadata is persisted. The API key lives in process
memory and is cleared whenever LifeContext stops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx


DEFAULT_CLOUD_CONFIG = {
    "enabled": False,
    "provider": "openai-compatible",
    "base_url": "https://api.openai.com/v1",
    "model": "",
    "timeout_seconds": 120,
}


class CloudLLM:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._api_key = ""

    def _load(self) -> dict[str, Any]:
        config: dict[str, Any] = {}
        if self.config_path.exists():
            try:
                config = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                config = {}
        return {**DEFAULT_CLOUD_CONFIG, **config}

    def public_config(self) -> dict[str, Any]:
        config = self._load()
        config["api_key_configured"] = bool(self._api_key)
        config["api_key"] = ""
        return config

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_url = str(payload.get("base_url", "")).strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be a valid HTTP(S) URL")
        model = str(payload.get("model", "")).strip()
        enabled = bool(payload.get("enabled"))
        api_key = str(payload.get("api_key", "")).strip()
        if not enabled:
            self._api_key = ""
        elif api_key:
            self._api_key = api_key
        if enabled and not model:
            raise ValueError("model is required when cloud inference is enabled")
        config = {
            "enabled": enabled,
            "provider": str(payload.get("provider") or "openai-compatible")[:80],
            "base_url": base_url,
            "model": model[:200],
            "timeout_seconds": max(10, min(int(payload.get("timeout_seconds", 120)), 600)),
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)
        return self.public_config()

    def enabled(self) -> bool:
        return bool(self._load().get("enabled"))

    def runtime_name(self) -> str:
        config = self._load()
        return f"cloud:{config['provider']}:{config['model']}"

    def _request(self, messages: list[dict[str, str]], parameters: dict[str, Any], stream: bool) -> tuple[str, dict[str, str], dict[str, Any], float]:
        config = self._load()
        if not config.get("enabled"):
            raise RuntimeError("Cloud inference is disabled")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": config["model"],
            "messages": messages,
            "stream": stream,
            "temperature": parameters.get("temperature", 0.68),
            "top_p": parameters.get("top_p", 0.95),
            "max_tokens": parameters.get("max_tokens", 700),
        }
        url = f"{config['base_url']}/chat/completions"
        return url, headers, body, float(config["timeout_seconds"])

    def chat(self, messages: list[dict[str, str]], **parameters: Any) -> str:
        url, headers, body, timeout = self._request(messages, parameters, False)
        response = httpx.post(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])

    def chat_stream(self, messages: list[dict[str, str]], **parameters: Any) -> Iterator[str]:
        url, headers, body, timeout = self._request(messages, parameters, True)
        with httpx.stream("POST", url, headers=headers, json=body, timeout=timeout) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                    text = payload["choices"][0].get("delta", {}).get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if text:
                    yield str(text)
