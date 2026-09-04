from pathlib import Path

from modelscope import snapshot_download
from modelscope.hub.api import ModelScopeConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
MODEL_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"

REQUIRED_FILES = [
    "configuration.json",
    "cosyvoice3.yaml",
    "campplus.onnx",
    "flow.pt",
    "hift.pt",
    "llm.pt",
    "speech_tokenizer_v3.onnx",
    "CosyVoice-BlankEN/*",
]


def main() -> None:
    ModelScopeConfig.path_credential = str(RUNTIME_DIR / "modelscope-credentials")
    path = snapshot_download(
        MODEL_ID,
        cache_dir=str(RUNTIME_DIR / "modelscope-cache"),
        allow_file_pattern=REQUIRED_FILES,
    )
    print(f"MODEL_DOWNLOAD_COMPLETE={path}", flush=True)


if __name__ == "__main__":
    main()
