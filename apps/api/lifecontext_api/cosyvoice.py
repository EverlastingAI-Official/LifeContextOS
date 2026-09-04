from io import BytesIO
import base64
from collections.abc import AsyncIterator
import wave

import httpx


class CosyVoiceClient:
    """Adapter for CosyVoice's official FastAPI zero-shot endpoint."""

    def __init__(self, base_url: str, timeout_seconds: float = 900) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds

    async def synthesize_zero_shot(
        self,
        *,
        tts_text: str,
        prompt_text: str,
        prompt_wav: bytes,
        prompt_filename: str,
    ) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/inference_zero_shot",
                # Multipart text decoding on the lightweight Windows runtime
                # is locale-dependent. Send UTF-8 text as ASCII base64 so
                # Chinese never becomes mojibake before tokenization.
                data={
                    "tts_text_b64": base64.b64encode(tts_text.encode("utf-8")).decode("ascii"),
                    "prompt_text_b64": base64.b64encode(prompt_text.encode("utf-8")).decode("ascii"),
                },
                files={
                    "prompt_wav": (
                        prompt_filename or "prompt.wav",
                        prompt_wav,
                        "audio/wav",
                    )
                },
            )
            response.raise_for_status()
            return response.content

    async def stream_zero_shot(
        self,
        *,
        tts_text: str,
        prompt_text: str,
        prompt_wav: bytes,
        prompt_filename: str,
    ) -> AsyncIterator[bytes]:
        """Yield raw 24 kHz mono PCM as soon as CosyVoice emits each chunk."""

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/inference_zero_shot",
                data={
                    "tts_text_b64": base64.b64encode(tts_text.encode("utf-8")).decode("ascii"),
                    "prompt_text_b64": base64.b64encode(prompt_text.encode("utf-8")).decode("ascii"),
                },
                files={
                    "prompt_wav": (
                        prompt_filename or "prompt.wav",
                        prompt_wav,
                        "audio/wav",
                    )
                },
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_raw():
                    if chunk:
                        yield chunk


def pcm16_mono_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap the raw int16 stream returned by the official server as a WAV file."""

    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()
