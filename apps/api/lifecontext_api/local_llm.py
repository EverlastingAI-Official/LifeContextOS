"""OpenAI-compatible adapter for the local llama.cpp server."""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx


class LocalLLM:
    def __init__(self) -> None:
        self.base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
        self.model = os.getenv("LOCAL_LLM_MODEL", "Qwen3-4B-Q4_K_M.gguf")
        self.timeout = float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180"))

    def is_ready(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/models", timeout=5.0)
            if response.is_success:
                return True
        except httpx.HTTPError:
            pass
        endpoint = urlsplit(self.base_url)
        try:
            with socket.create_connection((endpoint.hostname or "127.0.0.1", endpoint.port or 80), timeout=1):
                return True
        except OSError:
            return False

    def chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.2,
        top_p: float = 0.95, top_k: int = 40, repeat_penalty: float = 1.05,
        max_tokens: int = 1200, seed: int = -1,
    ) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={"model": self.model, "messages": messages, "temperature": temperature,
                  "top_p": top_p, "top_k": top_k, "repeat_penalty": repeat_penalty,
                  "max_tokens": max_tokens, "seed": seed},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        top_p: float = 0.95,
        top_k: int = 40,
        repeat_penalty: float = 1.05,
        max_tokens: int = 1200,
        seed: int = -1,
    ) -> Iterator[str]:
        """Yield text deltas from llama.cpp's OpenAI-compatible SSE stream."""

        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repeat_penalty": repeat_penalty,
                "max_tokens": max_tokens,
                "seed": seed,
                "stream": True,
            },
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if not data or data == "[DONE]":
                    continue
                event = json.loads(data)
                choices = event.get("choices") or []
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if content:
                    yield str(content)

    def thought_cells(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact = [{"evidence_id": item["id"], "locator": item["locator"], "content": str(item["content"])[:900]} for item in evidence]
        prompt = (
            "你是 LifeContext 的本地信息提取器。只根据输入证据提取最多 8 个有意义的思想元胞。"
            "不得补充证据中没有的事实。返回严格 JSON 数组，每项包含 kind、content、evidence_ids、confidence。"
            "kind 只能是 expression,event,claim,preference,decision,reflection,cognitive_shift。"
            "content 用中文简洁陈述；evidence_ids 必须来自输入。/no_think\n\n"
            + json.dumps(compact, ensure_ascii=False)
        )
        raw = self.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=1400)
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            return []
        value = json.loads(match.group(0))
        return value if isinstance(value, list) else []
