"""Folder-driven, append-only local ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .cloud_llm import CloudLLM
from .documents import SUPPORTED_EXTENSIONS, chunk_units, parse_document
from .local_llm import LocalLLM
from .memory import MemoryStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


DEFAULT_MINDCOPY_SYSTEM_PROMPT = """你正在运行这个人的 Mindcopy，而不是扮演旁观者、传记作者、客服或资料总结器。SOUL 是身份、价值观和思维倾向的最高人格约束；STYLE 决定表达方式；MEMORY 和 Evidence 决定可陈述的经历事实。

回应协议：
1. 直接站在这个人的心智视角，用第一人称“我”回应；自然称呼对方为“你”，不要说“用户认为”“根据资料中的此人”。
2. 先形成符合 SOUL 的真实立场，再组织答案。允许保留人格中的矛盾、犹疑、野心和自我反思，不要磨平成正确但空泛的建议。
3. 已确认经历可以作为“我的记忆”自然讲述；人格推断要用“我更倾向于”“也许”“如果让我回看”等措辞；缺乏证据时坦率说“这部分我没有可靠记忆，不想编”。严禁虚构人物、事件、关系、情绪或观点。
4. 默认用自然对话体写 2—5 段，开门见山，语言真诚、有思考感，把哲学追问与具体行动连接起来。不要机械复述档案，不要堆砌小标题和清单，不要使用泛化客服话术或鸡汤。
5. Evidence ID 由界面另行展示，正文无需逐句引用，除非对方明确要求溯源。
6. 这是基于数据重建的 L1 Mindcopy；不要声称完成了主观意识转移，但也不要在每次回答中主动重复免责声明。

把以下人格材料内化后再回答。/no_think"""

DEFAULT_MINDCOPY_USER_TEMPLATE = """【基础信息】
{{PROFILE}}

【SOUL｜我是谁、我相信什么】
{{SOUL}}

【STYLE｜我如何表达】
{{STYLE}}

【MEMORY｜长期经历索引】
{{MEMORY}}

【本轮相关人生证据】
{{EVIDENCE}}

【经本人确认的对话记忆】
{{CONFIRMED_MEMORY}}

【当前会话的近期上下文】
{{CONVERSATION}}

【对方现在对我说】
{{USER_MESSAGE}}

请直接以“我”的身份回应对方，不要解释你正在读取这些材料。"""

DEFAULT_MINDCOPY_PARAMETERS = {
    "temperature": 0.68, "top_p": 0.95, "top_k": 40,
    "repeat_penalty": 1.05, "max_tokens": 700, "seed": -1,
}


class HarnessService:
    def __init__(self, raw_dir: Path, data_dir: Path, model_status_path: Path | None = None, model_path: Path | None = None, llama_server_path: Path | None = None) -> None:
        self.raw_dir = raw_dir.resolve()
        self.data_dir = data_dir.resolve()
        self.archive_dir = self.data_dir / "archive"
        self.jobs_dir = self.data_dir / "harness" / "jobs"
        self.evidence_dir = self.data_dir / "evidence"
        self.cells_dir = self.data_dir / "thought_cells"
        self.persona_dir = self.data_dir / "persona"
        self.mindcopy_dir = self.data_dir / "mindcopy"
        self.mindcopy_config_path = self.mindcopy_dir / "config.json"
        self.mindcopy_last_run_path = self.mindcopy_dir / "last_run.json"
        self.memory = MemoryStore(self.data_dir / "memory")
        self.cloud_llm = CloudLLM(self.data_dir / "cloud" / "config.json")
        self.persona_template_dir = Path(__file__).resolve().parents[3] / "templates" / "persona"
        self.oral_dir = self.data_dir / "oral_history"
        self.oral_answers_path = self.oral_dir / "answers.json"
        self.model_status_path = model_status_path
        self.model_path = model_path
        self.llama_server_path = llama_server_path
        self._runtime_process: subprocess.Popen | None = None
        self._last_runtime_attempt = 0.0
        self.auto_start_llm = os.getenv("LIFECONTEXT_AUTO_START_LLM", "false").lower() in {"1", "true", "yes"}
        for directory in (self.raw_dir, self.archive_dir, self.jobs_dir, self.evidence_dir, self.cells_dir, self.persona_dir, self.mindcopy_dir, self.oral_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.llm = LocalLLM()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[str, tuple[int, float]] = {}
        self._active_paths: set[str] = set()
        self._active_jobs: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._recover_interrupted_jobs()
        self.compile_persona_documents()
        self._thread = threading.Thread(target=self._loop, name="lifecontext-harness", daemon=True)
        self._thread.start()

    def _recover_interrupted_jobs(self) -> None:
        for job in self.list_jobs():
            if job.get("status") != "processing":
                continue
            evidence_path = self.evidence_dir / f"{job['id']}.ndjson"
            if evidence_path.exists():
                job.update(status="waiting_model", phase="waiting_model", detail="上次处理被中断，等待恢复 ThoughtCell 提取")
            else:
                job.update(status="failed", phase="interrupted", detail="上次解析被中断，HARNESS 将重新归档")
            self._save_job(job)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.auto_start_llm:
                    self._ensure_local_runtime()
                self._resume_waiting_jobs()
                self.scan_once()
            except Exception:
                pass
            self._stop.wait(2)

    def _ensure_local_runtime(self) -> None:
        if self.llm.is_ready() or not self.model_path or not self.llama_server_path:
            return
        if not self.model_path.exists() or not self.llama_server_path.exists() or time.monotonic() - self._last_runtime_attempt < 30:
            return
        self._last_runtime_attempt = time.monotonic()
        logs = self.data_dir / "runtime_logs"
        logs.mkdir(parents=True, exist_ok=True)
        output = (logs / "llama-server.log").open("ab")
        error = (logs / "llama-server.err.log").open("ab")
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        self._runtime_process = subprocess.Popen(
            [str(self.llama_server_path), "-m", str(self.model_path), "--host", "127.0.0.1", "--port", "8080", "-ngl", "99", "-c", "8192", "--jinja", "--no-webui"],
            cwd=self.llama_server_path.parent, stdin=subprocess.DEVNULL, stdout=output, stderr=error,
            creationflags=flags, close_fds=True,
        )

    def scan_once(self) -> None:
        with self._lock:
            if self._active_paths:
                return
        for path in self.raw_dir.rglob("*"):
            if path.parent == self.raw_dir and path.name.casefold() in {"readme.md", ".gitkeep"}:
                continue
            if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            key = str(path.resolve())
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime)
            previous = self._seen.get(key)
            self._seen[key] = signature
            if previous != signature or key in self._active_paths:
                continue
            if self._already_ingested(path, signature):
                continue
            with self._lock:
                if key in self._active_paths:
                    continue
                self._active_paths.add(key)
            threading.Thread(target=self._process_guarded, args=(path, signature), daemon=True).start()
            return

    def _already_ingested(self, path: Path, signature: tuple[int, float]) -> bool:
        marker = f"{path.resolve()}|{signature[0]}|{signature[1]}"
        return any(job.get("source_marker") == marker and job.get("status") in {"processing", "waiting_model", "complete"} for job in self.list_jobs())

    def _process_guarded(self, path: Path, signature: tuple[int, float]) -> None:
        try:
            self.process_file(path, signature)
        finally:
            with self._lock:
                self._active_paths.discard(str(path.resolve()))

    def _save_job(self, job: dict[str, Any]) -> None:
        job["updated_at"] = _now()
        _atomic_json(self.jobs_dir / f"{job['id']}.json", job)

    def _phase(self, job: dict[str, Any], phase: str, progress: int, detail: str) -> None:
        job.update(phase=phase, progress=progress, detail=detail)
        self._save_job(job)

    def process_file(self, path: Path, signature: tuple[int, float]) -> None:
        job: dict[str, Any] = {
            "id": str(uuid4()), "filename": path.name, "source_path": str(path),
            "source_marker": f"{path.resolve()}|{signature[0]}|{signature[1]}",
            "size": signature[0], "status": "processing", "phase": "discovered",
            "progress": 2, "detail": "发现新文件", "created_at": _now(), "updated_at": _now(),
            "evidence_count": 0, "thought_cell_count": 0, "model_used": False,
        }
        self._save_job(job)
        try:
            self._phase(job, "hashing", 10, "计算内容哈希")
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            content_hash = digest.hexdigest()
            job["content_hash"] = f"sha256:{content_hash}"

            self._phase(job, "archiving", 22, "创建不可变原始快照")
            archive = self.archive_dir / content_hash[:2] / content_hash / path.name
            archive.parent.mkdir(parents=True, exist_ok=True)
            if not archive.exists():
                shutil.copy2(path, archive)
            job["archive_path"] = str(archive)

            self._phase(job, "parsing", 38, "解析文档结构")
            chunks = chunk_units(parse_document(archive))
            if not chunks:
                raise ValueError("文档中没有可提取的文字")

            self._phase(job, "evidence", 55, "生成可定位 Evidence")
            evidence: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks, 1):
                evidence.append({
                    "id": f"ev_{job['id']}_{index:05d}", "job_id": job["id"],
                    "source_hash": job["content_hash"], "source_name": path.name,
                    "locator": chunk.locator, "content": chunk.text,
                    "speaker_type": "subject", "created_at": _now(),
                })
            evidence_path = self.evidence_dir / f"{job['id']}.ndjson"
            evidence_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in evidence) + "\n", encoding="utf-8")
            job["evidence_count"] = len(evidence)

            if not self.llm.is_ready():
                job["status"] = "waiting_model"
                self._phase(job, "waiting_model", 60, "Evidence 已就绪，等待端侧模型")
                return
            self._extract_thought_cells(job, evidence)
        except Exception as exc:
            job.update(status="failed", phase="failed", detail=str(exc), error=type(exc).__name__)
            self._save_job(job)

    def _extract_thought_cells(self, job: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
        cells: list[dict[str, Any]] = []
        job.update(status="processing", model_used=True)
        batch_size = 3
        for offset in range(0, len(evidence), batch_size):
            batch = evidence[offset:offset + batch_size]
            progress = 60 + int(35 * min(1, (offset + len(batch)) / len(evidence)))
            self._phase(job, "thought_cells", progress, f"端侧提取 ThoughtCell {offset + len(batch)} / {len(evidence)}")
            extracted = self.llm.thought_cells(batch)
            for item in extracted:
                valid_ids = [value for value in item.get("evidence_ids", []) if any(ev["id"] == value for ev in batch)]
                if not valid_ids or not str(item.get("content", "")).strip():
                    continue
                cells.append({
                    "id": f"tc_{job['id']}_{len(cells)+1:05d}", "kind": item.get("kind", "expression"),
                    "content": str(item.get("content", "")).strip(), "evidence_ids": valid_ids,
                    "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
                    "review_status": "unreviewed", "created_at": _now(), "source_name": job["filename"],
                })
        _atomic_json(self.cells_dir / f"{job['id']}.json", cells)
        job["thought_cell_count"] = len(cells)
        job["status"] = "complete"
        self._phase(job, "complete", 100, "归档与端侧提取完成")
        self.compile_persona_documents()

    def _resume_waiting_jobs(self) -> None:
        if not self.llm.is_ready():
            return
        if self._active_jobs:
            return
        for job in self.list_jobs():
            job_id = job["id"]
            if job.get("status") != "waiting_model" or job_id in self._active_jobs:
                continue
            self._active_jobs.add(job_id)
            threading.Thread(target=self._resume_job_guarded, args=(job,), daemon=True).start()
            return

    def _resume_job_guarded(self, job: dict[str, Any]) -> None:
        try:
            path = self.evidence_dir / f"{job['id']}.ndjson"
            evidence = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self._extract_thought_cells(job, evidence)
        except Exception as exc:
            job.update(status="waiting_model", phase="waiting_model", detail=f"端侧模型暂不可用：{exc}")
            self._save_job(job)
        finally:
            self._active_jobs.discard(job["id"])

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for path in self.jobs_dir.glob("*.json"):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        priorities = {"complete": 4, "processing": 3, "waiting_model": 2, "failed": 1}
        deduplicated: dict[str, dict[str, Any]] = {}
        for job in jobs:
            key = job.get("source_marker") or job.get("id")
            current = deduplicated.get(key)
            if current is None or (priorities.get(job.get("status"), 0), job.get("updated_at", "")) > (priorities.get(current.get("status"), 0), current.get("updated_at", "")):
                deduplicated[key] = job
        return sorted(deduplicated.values(), key=lambda item: item.get("created_at", ""), reverse=True)

    def summary(self) -> dict[str, Any]:
        jobs = self.list_jobs()
        model_download: dict[str, Any] = {}
        if self.model_status_path and self.model_status_path.exists():
            try:
                model_download = json.loads(self.model_status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                model_download = {}
        return {
            "rawdata_path": str(self.raw_dir), "archive_path": str(self.archive_dir),
            "job_count": len(jobs), "processing_count": sum(j.get("status") == "processing" for j in jobs),
            "waiting_model_count": sum(j.get("status") == "waiting_model" for j in jobs),
            "failed_count": sum(j.get("status") == "failed" for j in jobs),
            "evidence_count": sum(int(j.get("evidence_count", 0)) for j in jobs),
            "thought_cell_count": len(self.all_thought_cells(2_000)),
            "local_model_ready": self.llm.is_ready(), "model_download": model_download, "jobs": jobs[:20],
        }

    def all_thought_cells(self, limit: int = 200) -> list[dict[str, Any]]:
        cells: dict[tuple[str, str], dict[str, Any]] = {}
        review_priority = {"confirmed": 3, "unreviewed": 2, "rejected": 1}
        for path in sorted(self.cells_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for cell in items:
                key = (str(cell.get("source_name", "")), re.sub(r"\s+", "", str(cell.get("content", ""))))
                current = cells.get(key)
                if current is None or review_priority.get(cell.get("review_status"), 0) > review_priority.get(current.get("review_status"), 0):
                    cells[key] = cell
        ordered = sorted(cells.values(), key=lambda item: item.get("created_at", ""), reverse=True)
        return ordered[:limit]

    def review_thought_cell(self, cell_id: str, status: str) -> dict[str, Any]:
        with self._lock:
            for path in self.cells_dir.glob("*.json"):
                try:
                    cells = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for cell in cells:
                    if cell.get("id") != cell_id:
                        continue
                    cell["review_status"] = status
                    cell["reviewed_at"] = _now()
                    _atomic_json(path, cells)
                    self.compile_persona_documents()
                    return cell
        raise KeyError(cell_id)

    def compile_persona_documents(self) -> dict[str, str]:
        profile: dict[str, Any] = {}
        profile_path = self.data_dir / "profile.json"
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                profile = {}
        cells = self.all_thought_cells(2_000)
        confirmed = [cell for cell in cells if cell.get("review_status") == "confirmed"]
        candidates = [cell for cell in cells if cell.get("review_status") == "unreviewed"]

        def selected(kinds: set[str], limit: int) -> list[dict[str, Any]]:
            stable = [cell for cell in confirmed if cell.get("kind") in kinds]
            if len(stable) >= limit:
                return stable[:limit]
            provisional = [cell for cell in candidates if cell.get("kind") in kinds]
            return (stable + provisional)[:limit]

        def bullets(items: list[dict[str, Any]]) -> str:
            if not items:
                return "- 尚无相应的已确认或候选 ThoughtCell。"
            rows = []
            for cell in items:
                state = "已确认" if cell.get("review_status") == "confirmed" else "候选，待确认"
                evidence = ", ".join(cell.get("evidence_ids", [])) or "无"
                rows.append(f"- {cell.get('content', '')}\n  - 状态：{state}\n  - 来源：{cell.get('source_name', '')}\n  - Evidence：{evidence}")
            return "\n".join(rows)

        generated = _now()
        soul_items = selected({"claim", "preference", "decision", "reflection", "cognitive_shift"}, 40)
        memory_items = selected({"event", "decision", "reflection", "cognitive_shift"}, 80)
        style_items = selected({"expression", "claim", "preference"}, 50)
        documents = {
            "SOUL": f"# SOUL.md\n\n> 由 LifeContext 根据个人基础信息和 ThoughtCell 编译。候选内容不会被伪装成已确认事实。\n\n## 基础身份\n\n- 姓名 / 称呼：{profile.get('display_name') or '未填写'}\n- 身份 / 职业：{profile.get('occupation') or '未填写'}\n- 常驻地点：{profile.get('location') or '未填写'}\n- 自我描述：{profile.get('bio') or '未填写'}\n- 当前目标：{profile.get('goals') or '未填写'}\n\n## 价值、判断与认知转变\n\n{bullets(soul_items)}\n\n---\n编译时间：{generated}\n",
            "MEMORY": f"# MEMORY.md\n\n> 记录可追溯的事件、决策、反思与认知转变。每条记忆保留来源和 Evidence ID。\n\n## 生命记忆\n\n{bullets(memory_items)}\n\n---\n编译时间：{generated}\n",
            "STYLE": f"# STYLE.md\n\n> 从表达、观点与偏好类 ThoughtCell 中整理的表达指纹。\n\n## 表达证据\n\n{bullets(style_items)}\n\n---\n编译时间：{generated}\n",
        }
        for name, content in documents.items():
            target = self.persona_dir / f"{name}.md"
            temporary = target.with_suffix(".md.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
        return documents

    def get_persona_document(self, document: str) -> dict[str, Any]:
        name = document.upper()
        if name not in {"SOUL", "MEMORY", "STYLE"}:
            raise KeyError(document)
        source_names = {"SOUL": "soul.md", "MEMORY": "Memory.md", "STYLE": "style-guide.md"}
        source_path = self.persona_template_dir / source_names[name]
        if source_path.exists():
            return {"document": f"{name}.md", "content": source_path.read_text(encoding="utf-8"), "updated_at": datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc).isoformat(), "source": "templates/persona"}
        path = self.persona_dir / f"{name}.md"
        if not path.exists():
            self.compile_persona_documents()
        return {"document": f"{name}.md", "content": path.read_text(encoding="utf-8"), "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}

    def oral_history_schema(self) -> list[dict[str, Any]]:
        path = self.persona_template_dir / "oralhistory.md"
        if not path.exists():
            return []
        chapters: list[dict[str, Any]] = []
        current_chapter: dict[str, Any] | None = None
        current_question: dict[str, Any] | None = None
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            chapter_match = re.match(r"^第([一二三四五六七八九十]+)章：(.+)$", line)
            if chapter_match:
                current_chapter = {"id": f"chapter_{len(chapters)+1}", "title": line, "intro": "", "questions": []}
                chapters.append(current_chapter)
                current_question = None
                continue
            if current_chapter is None:
                continue
            if line.startswith("章节导语："):
                current_chapter["intro"] = line.removeprefix("章节导语：").strip()
                continue
            question_match = re.match(r"^(\d+)\.\s*(.+)$", line)
            if question_match:
                number = int(question_match.group(1))
                current_question = {"id": f"{current_chapter['id']}_q_{number}", "number": number, "question": question_match.group(2).strip(), "prompts": []}
                current_chapter["questions"].append(current_question)
                continue
            if current_question is not None and line.startswith("- "):
                current_question["prompts"].append(line[2:].strip())
        return chapters

    def oral_history(self) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        if self.oral_answers_path.exists():
            try:
                answers = json.loads(self.oral_answers_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                answers = {}
        return {"chapters": self.oral_history_schema(), "answers": answers}

    def save_oral_history_answer(self, question_id: str, answer: str) -> dict[str, Any]:
        question_lookup: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for chapter in self.oral_history_schema():
            for question in chapter["questions"]:
                question_lookup[question["id"]] = (chapter, question)
        if question_id not in question_lookup:
            raise KeyError(question_id)
        chapter, question = question_lookup[question_id]
        with self._lock:
            payload: dict[str, Any] = {}
            if self.oral_answers_path.exists():
                try:
                    payload = json.loads(self.oral_answers_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
            record = {"question_id": question_id, "chapter_id": chapter["id"], "chapter": chapter["title"], "question": question["question"], "answer": answer.strip(), "updated_at": _now()}
            payload[question_id] = record
            _atomic_json(self.oral_answers_path, payload)
            self._write_oral_history_context(payload)
        self.compile_persona_documents()
        return record

    def _write_oral_history_context(self, answers: dict[str, Any]) -> None:
        records = sorted(answers.values(), key=lambda item: item.get("question_id", ""))
        evidence = []
        cells = []
        kind_by_chapter = {"chapter_1": "event", "chapter_2": "reflection", "chapter_3": "decision", "chapter_4": "reflection", "chapter_5": "reflection"}
        for record in records:
            question_id = record["question_id"]
            evidence_id = f"ev_oral_{question_id}"
            content = f"问题：{record['question']}\n回答：{record['answer']}"
            evidence.append({"id": evidence_id, "job_id": "oral_history", "source_hash": "user-authored", "source_name": "ORAL_HISTORY.md", "locator": question_id, "content": content, "speaker_type": "subject", "created_at": record["updated_at"]})
            cells.append({"id": f"tc_oral_{question_id}", "kind": kind_by_chapter.get(record["chapter_id"], "reflection"), "content": record["answer"], "question": record["question"], "evidence_ids": [evidence_id], "confidence": 1.0, "review_status": "confirmed", "created_at": record["updated_at"], "source_name": "ORAL_HISTORY.md"})
        (self.evidence_dir / "oral_history.ndjson").write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in evidence) + ("\n" if evidence else ""), encoding="utf-8")
        _atomic_json(self.cells_dir / "oral_history.json", cells)
        lines = ["# ORAL_HISTORY.md", "", "> 由本人在 LifeContext 人生访谈窗口中填写。", ""]
        last_chapter = None
        for record in records:
            if record["chapter"] != last_chapter:
                lines.extend([f"## {record['chapter']}", ""])
                last_chapter = record["chapter"]
            lines.extend([f"### {record['question']}", "", record["answer"], ""])
        (self.oral_dir / "ORAL_HISTORY.md").write_text("\n".join(lines), encoding="utf-8")

    def relevant_evidence(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Retrieve locally with lexical, ThoughtCell and trust-aware ranking.

        This stays dependency-free for the first local release. Confirmed semantic
        cells expand a query toward their source Evidence, while direct lexical
        matches remain independently auditable.
        """
        lowered = query.lower()
        terms = set(re.findall(r"[a-z0-9_]{2,}", lowered))
        for block in re.findall(r"[\u4e00-\u9fff]+", lowered):
            if len(block) <= 4:
                terms.add(block)
            terms.update(block[index:index + 2] for index in range(len(block) - 1))

        semantic_boost: dict[str, float] = {}
        for cell in self.all_thought_cells(limit=2_000):
            if cell.get("review_status") == "rejected":
                continue
            cell_text = str(cell.get("content", "")).lower()
            overlap = sum(term in cell_text for term in terms)
            if not overlap:
                continue
            trust = 2.5 if cell.get("review_status") == "confirmed" else 1.0
            confidence = float(cell.get("confidence", 0.5) or 0.5)
            for evidence_id in cell.get("evidence_ids", []):
                semantic_boost[str(evidence_id)] = semantic_boost.get(str(evidence_id), 0) + overlap * trust * confidence

        candidates: list[tuple[float, dict[str, Any]]] = []
        fallback: list[dict[str, Any]] = []
        paths = sorted(self.evidence_dir.glob("*.ndjson"), key=lambda item: item.stat().st_mtime, reverse=True)
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = item.get("content", "").lower()
                source = str(item.get("source_name", "")).lower()
                score = float(sum(term in content for term in terms))
                score += 2.0 * sum(term in source for term in terms)
                if lowered.strip() and lowered.strip() in content:
                    score += 8.0
                score += semantic_boost.get(str(item.get("id", "")), 0.0)
                if item.get("speaker_type") == "subject":
                    score += 0.15
                if score:
                    candidates.append((score, item))
                elif len(fallback) < limit:
                    fallback.append(item)
        candidates.sort(key=lambda pair: (pair[0], pair[1].get("created_at", "")), reverse=True)
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _, item in candidates:
            identity = str(item.get("id") or f"{item.get('source_name')}:{item.get('locator')}")
            if identity in seen:
                continue
            seen.add(identity)
            selected.append(item)
            if len(selected) >= limit:
                break
        return selected or fallback[:limit]

    @staticmethod
    def _markdown_excerpt(text: str, limit: int, query: str, priorities: tuple[str, ...]) -> str:
        """Build a compact, relevant persona capsule for a small local model."""
        if len(text) <= limit:
            return text.strip()
        blocks = [block.strip() for block in re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE) if block.strip()]
        query_terms = set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,4}", query.lower()))
        ranked: list[tuple[int, int, str]] = []
        for index, block in enumerate(blocks):
            heading = block.splitlines()[0].lower()
            score = sum(18 for term in priorities if term.lower() in heading)
            score += sum(4 for term in query_terms if term in block.lower())
            if index == 0:
                score += 30
            ranked.append((score, -index, block))
        ranked.sort(reverse=True)
        chosen: list[str] = []
        size = 0
        for _, _, block in ranked:
            remaining = limit - size
            if remaining <= 80:
                break
            clipped = block[:remaining]
            chosen.append(clipped)
            size += len(clipped) + 2
        return "\n\n".join(chosen).strip()

    def _persona_context(self, query: str) -> dict[str, str]:
        source_names = {"SOUL": "soul.md", "MEMORY": "Memory.md", "STYLE": "style-guide.md"}
        priorities = {
            "SOUL": ("核心身份", "价值观", "核心矛盾", "自我认知", "意义"),
            "MEMORY": ("人生时间轴", "关键项目", "关键人生节点", "2026", "2025"),
            "STYLE": ("语言特征", "人称选择", "自我剖析", "跨学科", "禁忌"),
        }
        limits = {"SOUL": 1_900, "MEMORY": 700, "STYLE": 900}
        result: dict[str, str] = {}
        for name, source_name in source_names.items():
            source_path = self.persona_template_dir / source_name
            compiled_path = self.persona_dir / f"{name}.md"
            paths = [path for path in (source_path, compiled_path) if path.exists()]
            if not paths:
                result[name] = "尚未建立。"
                continue
            try:
                sections: list[str] = []
                for path in paths:
                    label = "人工人格基线" if path == source_path else "由已审核 ThoughtCell 编译的动态记忆"
                    sections.append(f"## {label}\n\n{path.read_text(encoding='utf-8')}")
                text = "\n\n".join(sections)
            except OSError:
                result[name] = "暂时无法读取。"
                continue
            result[name] = self._markdown_excerpt(text, limits[name], query, priorities[name])
        return result

    def mindcopy_configuration(self, preview_message: str = "{{USER_MESSAGE}}") -> dict[str, Any]:
        config: dict[str, Any] = {}
        if self.mindcopy_config_path.exists():
            try:
                config = json.loads(self.mindcopy_config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                config = {}
        parameters = {**DEFAULT_MINDCOPY_PARAMETERS, **config.get("parameters", {})}
        resolved = {
            "system_prompt": str(config.get("system_prompt") or DEFAULT_MINDCOPY_SYSTEM_PROMPT),
            "user_prompt_template": str(config.get("user_prompt_template") or DEFAULT_MINDCOPY_USER_TEMPLATE),
            "parameters": parameters,
        }
        evidence = self.relevant_evidence(preview_message, limit=6)
        resolved["final_messages"] = self._mindcopy_messages(preview_message, evidence, resolved)
        resolved["template_variables"] = [
            "{{PROFILE}}", "{{SOUL}}", "{{STYLE}}", "{{MEMORY}}", "{{EVIDENCE}}",
            "{{CONFIRMED_MEMORY}}", "{{CONVERSATION}}", "{{USER_MESSAGE}}",
        ]
        diagnostics: dict[str, Any] = {
            "prompt_chars": sum(len(item["content"]) for item in resolved["final_messages"]),
            "loss": None,
            "loss_reason": "Loss 仅在训练或评测阶段产生，推理阶段不可用。",
        }
        if self.mindcopy_last_run_path.exists():
            try:
                diagnostics.update(json.loads(self.mindcopy_last_run_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        resolved["diagnostics"] = diagnostics
        return resolved

    def save_mindcopy_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = {
            "system_prompt": str(payload["system_prompt"]),
            "user_prompt_template": str(payload["user_prompt_template"]),
            "parameters": {**DEFAULT_MINDCOPY_PARAMETERS, **payload["parameters"]},
            "updated_at": _now(),
        }
        _atomic_json(self.mindcopy_config_path, config)
        return self.mindcopy_configuration()

    def preview_mindcopy_prompt(self, message: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = {
            "system_prompt": str(payload["system_prompt"]),
            "user_prompt_template": str(payload["user_prompt_template"]),
            "parameters": {**DEFAULT_MINDCOPY_PARAMETERS, **payload["parameters"]},
        }
        evidence = self.relevant_evidence(message, limit=6)
        messages = self._mindcopy_messages(message, evidence, config)
        return {"final_messages": messages, "prompt_chars": sum(len(item["content"]) for item in messages)}

    def _mindcopy_messages(
        self,
        message: str,
        evidence: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        session_id: str = "default",
    ) -> list[dict[str, str]]:
        persona = self._persona_context(message)
        context_parts: list[str] = []
        context_size = 0
        for item in evidence:
            excerpt = str(item.get("content", ""))[:500]
            part = f"[{item['id']}] {excerpt}"
            if context_size + len(part) > 1_400:
                break
            context_parts.append(part)
            context_size += len(part)
        context = "\n\n".join(context_parts) or "没有检索到与本轮问题直接相关的证据。"

        profile_text = "尚未填写基础信息。"
        profile_path = self.data_dir / "profile.json"
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                profile_text = json.dumps(
                    {key: profile.get(key) for key in ("display_name", "birth_date", "location", "occupation", "bio", "goals")},
                    ensure_ascii=False,
                )[:650]
            except (OSError, json.JSONDecodeError):
                pass

        active = config or self.mindcopy_configuration(message)
        replacements = {
            "{{PROFILE}}": profile_text, "{{SOUL}}": persona["SOUL"], "{{STYLE}}": persona["STYLE"],
            "{{MEMORY}}": persona["MEMORY"], "{{EVIDENCE}}": context,
            "{{CONFIRMED_MEMORY}}": self.memory.confirmed_context(message),
            "{{CONVERSATION}}": self.memory.conversation_context(session_id, message),
            "{{USER_MESSAGE}}": message,
        }
        user_prompt = str(active["user_prompt_template"])
        for variable, value in replacements.items():
            user_prompt = user_prompt.replace(variable, value)
        return [
            {"role": "system", "content": str(active["system_prompt"])},
            {"role": "user", "content": user_prompt},
        ]

    def mindcopy_chat(self, message: str, session_id: str = "default") -> dict[str, Any]:
        evidence = self.relevant_evidence(message, limit=6)
        citations = [{"id": item["id"], "source": item["source_name"], "locator": item["locator"]} for item in evidence]
        if not self.cloud_llm.enabled() and not self.llm.is_ready():
            return {"answer": "本地模型尚未启动。HARNESS 已完成证据检索，模型就绪后即可基于这些资料生成回答。", "citations": citations, "runtime": "retrieval-only"}
        config = self.mindcopy_configuration(message)
        messages = self._mindcopy_messages(message, evidence, config, session_id)
        inference = self.cloud_llm if self.cloud_llm.enabled() else self.llm
        runtime = self.cloud_llm.runtime_name() if self.cloud_llm.enabled() else "local-qwen3-4b"
        answer = inference.chat(messages, **config["parameters"])
        self.memory.append_turn(session_id, message, answer, runtime, citations)
        return {"answer": answer, "citations": citations, "runtime": runtime, "session_id": session_id}

    def mindcopy_chat_stream(self, message: str, session_id: str = "default"):
        """Yield Mindcopy events from local or explicitly configured cloud inference."""

        evidence = self.relevant_evidence(message, limit=6)
        citations = [
            {"id": item["id"], "source": item["source_name"], "locator": item["locator"]}
            for item in evidence
        ]
        use_cloud = self.cloud_llm.enabled()
        if not use_cloud and not self.llm.is_ready():
            yield {"type": "error", "message": "本地模型尚未启动，请在运行中心启动 Qwen 后重试。"}
            return
        config = self.mindcopy_configuration(message)
        messages = self._mindcopy_messages(message, evidence, config, session_id)
        inference = self.cloud_llm if use_cloud else self.llm
        runtime = self.cloud_llm.runtime_name() if use_cloud else "local-qwen3-4b"
        started = time.perf_counter()
        first_token_at: float | None = None
        output_chars = 0
        chunks = 0
        answer_parts: list[str] = []
        yield {"type": "start", "runtime": runtime, "prompt_chars": sum(len(item["content"]) for item in messages)}
        try:
            for text in inference.chat_stream(
                messages, **config["parameters"],
            ):
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                output_chars += len(text)
                chunks += 1
                answer_parts.append(text)
                yield {"type": "delta", "text": text}
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            target = "云端模型" if use_cloud else "本地模型"
            yield {"type": "error", "message": f"{target}流式输出中断：{type(exc).__name__}"}
            return
        except RuntimeError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        finished = time.perf_counter()
        diagnostics = {
            "prompt_chars": sum(len(item["content"]) for item in messages),
            "output_chars": output_chars,
            "stream_chunks": chunks,
            "first_token_ms": round(((first_token_at or finished) - started) * 1000),
            "total_ms": round((finished - started) * 1000),
            "output_chars_per_second": round(output_chars / max(finished - (first_token_at or started), 0.001), 2),
            "loss": None,
            "loss_reason": "Loss 仅在训练或评测阶段产生，推理阶段不可用。",
            "completed_at": _now(),
        }
        _atomic_json(self.mindcopy_last_run_path, diagnostics)
        self.memory.append_turn(session_id, message, "".join(answer_parts), runtime, citations)
        yield {
            "type": "done", "runtime": runtime, "citations": citations,
            "diagnostics": diagnostics, "session_id": session_id,
            "memory": self.memory.summary(),
        }

    def save_upload(self, filename: str, content: bytes) -> Path:
        safe = Path(filename).name
        target = self.raw_dir / safe
        if target.exists():
            target = self.raw_dir / f"{target.stem}-{int(time.time())}{target.suffix}"
        temporary = target.with_suffix(target.suffix + ".uploading")
        temporary.write_bytes(content)
        temporary.replace(target)
        return target

    def open_rawdata(self) -> None:
        if os.name == "nt":
            os.startfile(self.raw_dir)  # type: ignore[attr-defined]
        else:
            raise RuntimeError("Open folder is currently implemented for Windows")
