"""Low-latency LifeContext runtime for CosyVoice3."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import threading
import tempfile
import time
from pathlib import Path

os.environ.setdefault("WINDIR", os.environ.get("SystemRoot", r"C:\Windows"))

ROOT = Path(__file__).resolve().parents[1]
COSY_ROOT = ROOT / ".runtime" / "CosyVoice"
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(COSY_ROOT))
sys.path.insert(0, str(COSY_ROOT / "third_party" / "Matcha-TTS"))

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from cosyvoice.cli.cosyvoice import AutoModel
from lifecontext_api.tts_segmentation import pause_seconds_after, segment_for_speech


app = FastAPI(title="LifeContext CosyVoice Streaming Runtime")
state: dict[str, object] = {
    "status": "loading",
    "device": "detecting",
    "fp16": False,
    "sample_rate": 24000,
    "cached_voices": 0,
    "cache_hits": 0,
    "error": None,
}
cosyvoice = None
inference_lock = threading.Lock()
voice_cache: dict[str, str] = {}
speaker_cache_dir = ROOT / ".runtime" / "cosyvoice-cache" / "speakers"


def load_model(model_dir: str) -> None:
    global cosyvoice
    try:
        use_cuda = torch.cuda.is_available() and os.getenv("COSYVOICE_DEVICE", "auto") != "cpu"
        state.update(device="cuda" if use_cuda else "cpu", fp16=use_cuda)
        cosyvoice = AutoModel(
            model_dir=model_dir,
            fp16=use_cuda,
            load_trt=False,
            load_vllm=False,
        )
        stream_hop = max(10, int(os.getenv("COSYVOICE_STREAM_HOP", "10")))
        cosyvoice.model.token_hop_len = stream_hop
        cosyvoice.model.token_max_hop_len = stream_hop * 4
        cosyvoice.model.stream_scale_factor = 2
        state.update(
            status="ready",
            sample_rate=int(cosyvoice.sample_rate),
            stream_hop=stream_hop,
            gpu_name=torch.cuda.get_device_name(0) if use_cuda else None,
        )
    except Exception as exc:
        state.update(status="error", error=f"{type(exc).__name__}: {exc}")


def generate_data(model_output):
    for item in model_output:
        speech = item["tts_speech"].detach().float().cpu().numpy()
        yield (np.clip(speech, -1.0, 1.0) * (2**15 - 1)).astype(np.int16).tobytes()


def cache_voice(prompt_text: str, prompt_bytes: bytes, prompt_path: str) -> tuple[str, bool]:
    """Encode a reference recording once and reuse it across requests/restarts."""

    cache_key = hashlib.sha256(prompt_text.encode("utf-8") + b"\0" + prompt_bytes).hexdigest()
    speaker_id = voice_cache.get(cache_key)
    if speaker_id is not None:
        state["cache_hits"] = int(state["cache_hits"]) + 1
        state["last_cache_source"] = "memory"
        return speaker_id, True
    speaker_id = f"lifecontext_{cache_key[:24]}"
    speaker_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = speaker_cache_dir / f"{cache_key}.pt"
    if cache_path.exists():
        cosyvoice.frontend.spk2info[speaker_id] = torch.load(
            cache_path, map_location="cpu", weights_only=True
        )
        voice_cache[cache_key] = speaker_id
        state["cached_voices"] = len(voice_cache)
        state["cache_hits"] = int(state["cache_hits"]) + 1
        state["last_cache_source"] = "disk"
        return speaker_id, True
    cosyvoice.add_zero_shot_spk(prompt_text, prompt_path, speaker_id)
    speaker_data = {
        key: value.detach().cpu() if torch.is_tensor(value) else value
        for key, value in cosyvoice.frontend.spk2info[speaker_id].items()
    }
    temporary_cache = cache_path.with_suffix(".pt.tmp")
    torch.save(speaker_data, temporary_cache)
    temporary_cache.replace(cache_path)
    voice_cache[cache_key] = speaker_id
    state["cached_voices"] = len(voice_cache)
    state["last_cache_source"] = "encoded"
    return speaker_id, False


@app.get("/health")
def health() -> dict[str, object]:
    return state


@app.post("/inference_zero_shot")
async def inference_zero_shot(
    tts_text: str | None = Form(default=None),
    prompt_text: str | None = Form(default=None),
    tts_text_b64: str | None = Form(default=None),
    prompt_text_b64: str | None = Form(default=None),
    prompt_wav: UploadFile = File(),
):
    if state["status"] != "ready" or cosyvoice is None:
        raise HTTPException(status_code=503, detail=state)
    prompt_bytes = await prompt_wav.read()
    if not prompt_bytes:
        raise HTTPException(status_code=400, detail="Prompt audio is empty")
    try:
        if tts_text_b64:
            tts_text = base64.b64decode(tts_text_b64).decode("utf-8")
        if prompt_text_b64:
            prompt_text = base64.b64decode(prompt_text_b64).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid UTF-8 text payload") from exc
    if not tts_text or prompt_text is None:
        raise HTTPException(status_code=400, detail="tts_text and prompt_text are required")
    temp_dir = ROOT / ".runtime" / "cosyvoice-cache" / "uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", dir=temp_dir, delete=False) as temp:
        temp.write(prompt_bytes)
        prompt_path = temp.name
    if "<|endofprompt|>" not in prompt_text:
        prompt_text = "You are a helpful assistant.<|endofprompt|>" + prompt_text.strip()

    # Registration must finish before the temporary upload can be removed.
    # The inference lock also prevents two GPU jobs from corrupting the model's
    # shared streaming caches.
    inference_lock.acquire()
    try:
        speaker_id, cache_hit = cache_voice(prompt_text, prompt_bytes, prompt_path)
    except Exception:
        inference_lock.release()
        raise
    finally:
        Path(prompt_path).unlink(missing_ok=True)

    def stream_pcm():
        started = time.perf_counter()
        chunks = 0
        segments = segment_for_speech(tts_text)
        try:
            for segment_index, segment in enumerate(segments):
                # Synthesize one complete punctuation-bounded segment at a time.
                # Sentence-level streaming is more stable than tiny token chunks
                # and keeps pauses aligned with the semantics of the text.
                cosyvoice.model.token_hop_len = int(state.get("stream_hop", 10))
                output = cosyvoice.inference_zero_shot(
                    segment,
                    "",
                    "",
                    zero_shot_spk_id=speaker_id,
                    stream=False,
                    text_frontend=False,
                )
                for pcm in generate_data(output):
                    if pcm:
                        chunks += 1
                        yield pcm
                if segment_index < len(segments) - 1:
                    pause_samples = round(float(cosyvoice.sample_rate) * pause_seconds_after(segment))
                    yield np.zeros(pause_samples, dtype=np.int16).tobytes()
            if chunks == 0:
                raise RuntimeError("CosyVoice returned no audio chunks")
        finally:
            state.update(
                last_generation_seconds=round(time.perf_counter() - started, 3),
                last_generation_chunks=chunks,
                last_segment_count=len(segments),
                segmentation="punctuation",
                last_cache_hit=cache_hit,
            )
            inference_lock.release()

    return StreamingResponse(
        stream_pcm(),
        media_type="application/octet-stream",
        headers={
            "X-Audio-Sample-Rate": str(cosyvoice.sample_rate),
            "X-Audio-Format": "pcm_s16le",
            "X-Voice-Cache": "hit" if cache_hit else "miss",
            "X-TTS-Segmentation": "punctuation",
            "Cache-Control": "no-store",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--port", type=int, default=50000)
    args = parser.parse_args()
    threading.Thread(target=load_model, args=(args.model_dir,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
