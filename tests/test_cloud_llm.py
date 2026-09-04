import json

import pytest

from lifecontext_api.cloud_llm import CloudLLM


def test_cloud_config_persists_metadata_but_not_secret(tmp_path):
    path = tmp_path / "cloud" / "config.json"
    client = CloudLLM(path)
    result = client.configure({
        "enabled": True,
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1/",
        "model": "deepseek-chat",
        "api_key": "secret-value",
        "timeout_seconds": 90,
    })

    assert result["api_key_configured"] is True
    assert result["api_key"] == ""
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "api_key" not in persisted
    assert "secret-value" not in path.read_text(encoding="utf-8")
    assert persisted["base_url"] == "https://api.deepseek.com/v1"


def test_cloud_config_rejects_invalid_url(tmp_path):
    client = CloudLLM(tmp_path / "config.json")
    with pytest.raises(ValueError):
        client.configure({"enabled": True, "base_url": "not-a-url", "model": "x"})
