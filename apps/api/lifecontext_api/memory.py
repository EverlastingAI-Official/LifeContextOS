"""Local-first conversational and candidate memory for Mindcopy.

The store deliberately separates a conversation transcript from durable identity
memory.  A user message may become a *candidate*, but it is never promoted into
the reviewed persona without an explicit review action.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_session_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", value.strip())[:80]
    return cleaned or "default"


def _terms(text: str) -> set[str]:
    lowered = text.lower()
    result = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    for block in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(block) <= 4:
            result.add(block)
        result.update(block[index:index + 2] for index in range(len(block) - 1))
    return result


class MemoryStore:
    """Append-only local conversation log plus review-gated memory candidates."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sessions_dir = self.root / "sessions"
        self.candidates_dir = self.root / "candidates"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{_safe_session_id(session_id)}.ndjson"

    def turns(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-max(1, min(limit, 2_000)):]

    def append_turn(
        self,
        session_id: str,
        user: str,
        assistant: str,
        runtime: str,
        citations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        record = {
            "id": f"turn_{uuid4().hex}",
            "session_id": _safe_session_id(session_id),
            "user": user,
            "assistant": assistant,
            "runtime": runtime,
            "citations": citations,
            "created_at": _now(),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        path = self._session_path(session_id)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        self._capture_candidate(session_id, user, record["id"])
        return record

    def conversation_context(self, session_id: str, query: str, max_chars: int = 2_400) -> str:
        records = self.turns(session_id)
        if not records:
            return "这是本次会话的第一轮，没有更早的对话记忆。"

        recent = records[-6:]
        recent_ids = {item["id"] for item in recent}
        query_terms = _terms(query)
        older_ranked: list[tuple[int, dict[str, Any]]] = []
        for item in records[:-6]:
            text = f"{item.get('user', '')} {item.get('assistant', '')}".lower()
            score = sum(term in text for term in query_terms)
            if score:
                older_ranked.append((score, item))
        older_ranked.sort(key=lambda pair: pair[0], reverse=True)
        selected = [item for _, item in older_ranked[:2] if item["id"] not in recent_ids] + recent

        parts: list[str] = []
        size = 0
        for item in selected:
            part = f"对方：{item.get('user', '')}\n我：{item.get('assistant', '')}"
            if size + len(part) > max_chars:
                remaining = max_chars - size
                if remaining > 120:
                    parts.append(part[:remaining])
                break
            parts.append(part)
            size += len(part) + 2
        return "\n\n".join(parts)

    @staticmethod
    def _candidate_kind(text: str) -> str | None:
        patterns = {
            "preference": ("我喜欢", "我不喜欢", "我偏好", "我更喜欢", "我的习惯"),
            "decision": ("我决定", "我打算", "我的目标", "以后我要", "记住我会"),
            "identity": ("我是一个", "我的职业", "我的名字", "我出生", "请记住我是"),
            "event": ("我经历过", "我曾经", "我去了", "我完成了", "发生在我"),
        }
        for kind, markers in patterns.items():
            if any(marker in text for marker in markers):
                return kind
        if "记住" in text or "记得" in text:
            return "reflection"
        return None

    def _capture_candidate(self, session_id: str, text: str, turn_id: str) -> None:
        kind = self._candidate_kind(text)
        if not kind:
            return
        record = {
            "id": f"mc_{uuid4().hex}",
            "kind": kind,
            "content": text,
            "session_id": _safe_session_id(session_id),
            "turn_id": turn_id,
            "source_type": "conversation",
            "confidence": 0.7,
            "review_status": "unreviewed",
            "valid_from": None,
            "valid_to": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        path = self.candidates_dir / f"{record['id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def candidates(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self.candidates_dir.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status and item.get("review_status") != status:
                continue
            records.append(item)
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records[:max(1, min(limit, 2_000))]

    def review_candidate(self, candidate_id: str, status: str) -> dict[str, Any]:
        if status not in {"confirmed", "rejected", "unreviewed"}:
            raise ValueError("Unsupported review status")
        path = self.candidates_dir / f"{Path(candidate_id).name}.json"
        if not path.exists():
            raise KeyError(candidate_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["review_status"] = status
        record["updated_at"] = _now()
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return record

    def confirmed_context(self, query: str, limit: int = 5) -> str:
        terms = _terms(query)
        ranked: list[tuple[int, str]] = []
        for item in self.candidates(status="confirmed", limit=2_000):
            content = str(item.get("content", ""))
            score = 2 + sum(term in content.lower() for term in terms)
            ranked.append((score, content))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return "\n".join(f"- {content}" for _, content in ranked[:limit]) or "暂无经本人确认的对话记忆。"

    def summary(self) -> dict[str, Any]:
        session_count = len(list(self.sessions_dir.glob("*.ndjson")))
        candidates = self.candidates(limit=2_000)
        return {
            "storage": "local",
            "sessions": session_count,
            "candidate_count": len(candidates),
            "unreviewed_count": sum(item.get("review_status") == "unreviewed" for item in candidates),
            "confirmed_count": sum(item.get("review_status") == "confirmed" for item in candidates),
            "layers": ["archive", "evidence", "thought_cell", "persona", "conversation", "working_context"],
        }
