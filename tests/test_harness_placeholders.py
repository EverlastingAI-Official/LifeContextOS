from lifecontext_api.harness import HarnessService


def test_rawdata_readme_is_not_ingested(tmp_path) -> None:
    raw = tmp_path / "RAWDATA"
    raw.mkdir()
    (raw / "README.md").write_text("Drop personal files here.", encoding="utf-8")

    harness = HarnessService(raw, tmp_path / "data")
    harness.scan_once()
    harness.scan_once()

    assert harness.list_jobs() == []

