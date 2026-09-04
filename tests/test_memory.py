import json

from lifecontext_api.memory import MemoryStore


def test_conversation_memory_and_review_gate(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    store.append_turn("session/a", "我喜欢简约科技风。", "我记下了，但会等待你确认。", "local", [])

    turns = store.turns("session/a")
    assert len(turns) == 1
    assert "简约科技风" in store.conversation_context("session/a", "设计偏好")

    candidates = store.candidates(status="unreviewed")
    assert len(candidates) == 1
    assert candidates[0]["kind"] == "preference"
    assert store.confirmed_context("设计") == "暂无经本人确认的对话记忆。"

    reviewed = store.review_candidate(candidates[0]["id"], "confirmed")
    assert reviewed["review_status"] == "confirmed"
    assert "简约科技风" in store.confirmed_context("设计")


def test_api_output_is_not_reclassified_as_user_memory(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    store.append_turn("default", "你好", "我喜欢虚构出来的偏好。", "cloud:test", [])
    assert store.candidates() == []
    line = (tmp_path / "memory" / "sessions" / "default.ndjson").read_text(encoding="utf-8")
    assert json.loads(line)["runtime"] == "cloud:test"
