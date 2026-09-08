"""WAV loading for CosyVoice without TorchAudio's optional TorchCodec decoder."""

import soundfile as sf
import torch
import torchaudio


def load_wav(wav, target_sr, min_sr=16000):
    samples, sample_rate = sf.read(wav, dtype="float32", always_2d=True)
    speech = torch.from_numpy(samples.T.copy()).mean(dim=0, keepdim=True)
    if sample_rate != target_sr:
        if sample_rate < min_sr:
            raise ValueError(f"WAV sample rate {sample_rate} must be at least {min_sr}")
        speech = torchaudio.transforms.Resample(sample_rate, target_sr)(speech)
    return speech
