"""Speech inside the App Lab container: whisper.cpp tiny.en (pywhispercpp) in, Piper out.
Both models download once into MODELS on first start; after that everything runs offline.
Microphone and speaker come from arduino.app_peripherals (wired up in main.py)."""
import os
import re
import time
from pathlib import Path

import numpy as np

MODELS = os.environ.get("JARVIS_MODELS", "/app/data/models")
WHISPER_MODEL = "tiny.en"
PIPER_VOICE = "en_GB-northern_english_male-medium"  # swap for any Piper voice name
RATE = 16000  # whisper wants 16 kHz mono


class Voice:
    def __init__(self, models=MODELS):
        from pywhispercpp.model import Model
        from piper import PiperVoice
        from piper.download_voices import download_voice

        os.makedirs(models, exist_ok=True)
        self.stt = Model(WHISPER_MODEL, models_dir=models, n_threads=4, print_progress=False,
                         print_realtime=False)
        onnx = Path(models) / f"{PIPER_VOICE}.onnx"
        if not onnx.exists():
            download_voice(PIPER_VOICE, Path(models))
        self.tts = PiperVoice.load(onnx)
        self.tts_rate = self.tts.config.sample_rate

    def transcribe(self, pcm):
        """int16 mono 16 kHz samples -> (text, seconds). Whisper's [BLANK_AUDIO]-style tags are dropped."""
        t0 = time.time()
        audio = pcm.astype(np.float32).ravel() / 32768.0
        # audio_ctx=512 (~10 s window) instead of the default 30 s: 4.8 s -> 1.4 s on the UNO Q,
        # same transcripts (docs/measurements.md). Recordings are 5 s, so nothing is cut off.
        text = " ".join(s.text for s in self.stt.transcribe(audio, audio_ctx=512))
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text).strip()
        return text, time.time() - t0

    def synth(self, text):
        """text -> (int16 samples at self.tts_rate, seconds)."""
        t0 = time.time()
        audio = np.concatenate([c.audio_int16_array for c in self.tts.synthesize(text)])
        return audio, time.time() - t0
