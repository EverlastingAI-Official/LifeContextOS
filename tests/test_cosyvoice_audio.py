import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import numpy as np
    import soundfile as sf
    from cosyvoice_audio import load_wav
except ModuleNotFoundError:
    load_wav = None


@unittest.skipIf(load_wav is None, "Run with the CosyVoice runtime's Python")
class ReferenceAudioTests(unittest.TestCase):
    def test_stereo_wav_resamples_without_torchcodec(self):
        audio = io.BytesIO()
        samples = np.column_stack((np.full(16000, 0.25), np.full(16000, 0.75)))
        sf.write(audio, samples, 16000, format="WAV", subtype="PCM_16")
        audio.seek(0)
        with patch("torchaudio.load", side_effect=ImportError("TorchCodec is required")):
            speech = load_wav(audio, 24000)
        self.assertEqual(tuple(speech.shape), (1, 24000))
        self.assertAlmostEqual(float(speech[0, 12000]), 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
