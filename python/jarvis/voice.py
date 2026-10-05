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
PIPER_VOICE = "en_GB-northern_english_male-medium"  # picked by ear over alan and semaine (they sounded like a villain)
SLOW = 1.3   # Piper length_scale: <1 brisker, >1 slower
ECHO = 0.0   # short "voice in the walls" echo gain; above ~0.2 it starts to sound sinister
RATE = 16000  # whisper wants 16 kHz mono
PEAK = 24000  # output normalised to this (of 32767); 31000 sounded unclear on the Bluetooth speaker


def until_quiet(chunks, rate=RATE, max_s=6.0, quiet_s=0.8, wait_s=4.0):
    """Collect mic chunks until the person stops talking, instead of a fixed 5 s window.
    Speech = chunk RMS above 2.5x the quietest chunk so far (floor ~1000 at full gain on the camera mic),
    clamped to 1500..3000. Stops after quiet_s of quiet following speech, after wait_s if nobody spoke,
    or at max_s."""
    got, n, floor, spoke, quiet = [], 0, None, False, 0
    for c in chunks:
        got.append(c)
        n += len(c)
        rms = float(np.sqrt(np.mean(c.astype(np.float32) ** 2)))
        floor = rms if floor is None else min(floor, rms)
        if rms > min(3000.0, max(1500.0, 2.5 * floor)):
            spoke, quiet = True, 0
        else:
            quiet += len(c)
        if n >= max_s * rate or (spoke and quiet >= quiet_s * rate) or (not spoke and n >= wait_s * rate):
            break
    return np.concatenate(got)


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
        # same transcripts (docs/measurements.md). Recordings are 6 s at most, so nothing is cut off.
        text = " ".join(s.text for s in self.stt.transcribe(audio, audio_ctx=512))
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", text).strip()
        return text, time.time() - t0

    def synth(self, text):
        """text -> (int16 samples at self.tts_rate, seconds)."""
        from piper import SynthesisConfig
        t0 = time.time()
        cfg = SynthesisConfig(length_scale=SLOW)  # default noise_scale: natural, warm intonation
        x = np.concatenate([c.audio_int16_array for c in self.tts.synthesize(text, cfg)]).astype(np.float32)
        d = int(0.015 * self.tts_rate)  # 15 ms and 30 ms taps
        y = x.copy()
        y[d:] += ECHO * x[:-d]
        y[2 * d:] += ECHO / 2 * x[:-2 * d]
        y *= PEAK / max(1.0, float(np.abs(y).max()))  # normalise loud: the BT speaker is quiet
        return y.astype(np.int16), time.time() - t0
