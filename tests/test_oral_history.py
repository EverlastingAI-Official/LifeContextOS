from lifecontext_api.harness import HarnessService


def test_interview_templates_load_with_external_data_directory(tmp_path):
    harness = HarnessService(tmp_path / "raw", tmp_path / "personal" / "data")

    chapters = harness.oral_history()["chapters"]
    assert chapters
    question = chapters[0]["questions"][0]
    answer = "这是一条用于回归验证的虚构回答。"
    harness.save_oral_history_answer(question["id"], answer)

    reopened = HarnessService(tmp_path / "raw", tmp_path / "personal" / "data")
    assert reopened.oral_history()["answers"][question["id"]]["answer"] == answer
    assert answer in (harness.evidence_dir / "oral_history.ndjson").read_text(encoding="utf-8")
    for name in ("SOUL", "MEMORY", "STYLE"):
        document = reopened.get_persona_document(name)
        assert document["source"] == "templates/persona"
        assert document["content"].strip()
