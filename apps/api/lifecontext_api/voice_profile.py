from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import wave


class VoiceProfileError(ValueError):
    pass


class VoiceProfileStore:
    """Local reference-voice store with explicit consent and WAV validation."""

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "voice"
        self.root.mkdir(parents=True, exist_ok=True)
        self.audio_path = self.root / "reference.wav"
        self.metadata_path = self.root / "profile.json"

    def get(self) -> dict:
        if not self.metadata_path.exists() or not self.audio_path.exists():
            return {"configured": False}
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"configured": False}
        payload["configured"] = True
        return payload

    def save(self, *, filename: str, audio: bytes, reference_text: str, confirmed: bool) -> dict:
        if not confirmed:
            raise VoiceProfileError("Voice cloning requires confirmation that you own or may use this voice.")
        if Path(filename).suffix.lower() != ".wav":
            raise VoiceProfileError("The current local runtime accepts PCM WAV reference audio only.")
        if not reference_text.strip():
            raise VoiceProfileError("Reference text is required and must match the recording word for word.")
        if len(audio) > 25 * 1024 * 1024:
            raise VoiceProfileError("Reference audio must be smaller than 25 MB.")
        try:
            with wave.open(BytesIO(audio), "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                frames = source.getnframes()
                compression = source.getcomptype()
        except (wave.Error, EOFError) as exc:
            raise VoiceProfileError("The file is not a readable PCM WAV audio file.") from exc
        duration = frames / sample_rate if sample_rate else 0
        if compression != "NONE" or sample_width != 2:
            raise VoiceProfileError("Please use uncompressed 16-bit PCM WAV audio.")
        if channels not in {1, 2}:
            raise VoiceProfileError("Reference audio must be mono or stereo.")
        if sample_rate < 16_000:
            raise VoiceProfileError("Reference audio sample rate must be at least 16 kHz.")
        if not 3 <= duration <= 30:
            raise VoiceProfileError("Reference audio must be between 3 and 30 seconds.")

        temporary_audio = self.audio_path.with_suffix(".wav.tmp")
        temporary_audio.write_bytes(audio)
        temporary_audio.replace(self.audio_path)
        payload = {
            "configured": True,
            "filename": Path(filename).name,
            "reference_text": reference_text.strip(),
            "duration_seconds": round(duration, 2),
            "sample_rate": sample_rate,
            "channels": channels,
            "format": "PCM WAV 16-bit",
            "consent_confirmed": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary_metadata = self.metadata_path.with_suffix(".json.tmp")
        temporary_metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_metadata.replace(self.metadata_path)
        return payload

    def audio(self) -> bytes:
        if not self.audio_path.exists():
            raise VoiceProfileError("No reference voice has been configured.")
        return self.audio_path.read_bytes()
