"""JARVIS on the UNO Q (App Lab entry point).
Always listening: wake word -> greeting -> record the request -> whisper -> keyword rules, Gemma if they give up (one JSON action)
-> validate() -> laser / box LED -> Piper reply. Loans and returns wait for a spoken yes or a tap."""
import os
import re
import subprocess
import threading
import time

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App

from jarvis import db
from jarvis.dashboard import state
from jarvis.engine import Engine
from jarvis.hardware import BridgeHardware
from jarvis.llm import HybridLLM, LlamaServerLLM

DATA = "/app/data"
# Label inside the keyword model. "hey_arduino" is App Lab's built-in model, so the wake flow works out
# of the box; switch to "hey_jarvis" once the custom Edge Impulse model is installed and selected.
WAKE_WORD = os.environ.get("JARVIS_WAKE_WORD", "hey_arduino")
LISTEN_SECONDS = 5

os.makedirs(DATA, exist_ok=True)
con = db.connect(f"{DATA}/jarvis.db")
db.seed(con)
hw = BridgeHardware()
# Gemma only sees requests the keyword rules can't handle; it takes ~28 s here, so say so first.
engine = Engine(con, HybridLLM(LlamaServerLLM(), on_slow=lambda: speak("One moment, sir. Running the calculations.")), hw)
voice = None  # loaded in the background: first start downloads ~136 MB of speech models
busy = threading.Lock()


def ring(s):
    try:
        hw.ring_state(s)
    except Exception as e:  # a missing MCU must not stop the conversation
        print("[bridge]", e)


def open_speaker():
    """USB/jack speaker if plugged, else the first connected Bluetooth speaker (App Lab doesn't auto-pick BT)."""
    from arduino.app_peripherals.speaker import Speaker
    try:
        return Speaker(sample_rate=voice.tts_rate)
    except Exception:
        dump = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r'"node.name": "(bluez_output[^"]*)"', dump)
        if not m:
            raise
        return Speaker(device=f"pipewire:NODE={m.group(1)}", sample_rate=voice.tts_rate)


def speak(text):
    print("JARVIS>", text)
    if voice is None:
        return
    try:
        with open_speaker() as sp:  # open first: no speaker -> skip the ~2 s synth, mic opens at once
            audio, t = voice.synth(text)
            ring("speaking")
            sp.play_pcm(audio)
            time.sleep(0.5)  # play_pcm returns ~0.2 s early and BT adds latency: let the tail finish before the mic opens
        print(f"[timing] tts={t:.2f}s audio={len(audio) / voice.tts_rate:.1f}s")
    except Exception as e:
        print("[speaker]", e)


def listen():
    from arduino.app_peripherals.microphone import Microphone
    ring("listening")
    with Microphone(device=0) as mic:  # device 0 = shared with the wake-word brick
        pcm = mic.record_pcm(LISTEN_SECONDS)
    ring("thinking")
    text, t = voice.transcribe(pcm)
    print(f"[timing] stt={t:.2f}s peak={int(abs(pcm).max())} heard={text!r}")  # peak: 0..32767, near 0 = silence
    return text


def conversation():
    """One wake-up: greet, then keep going (requests, yes/no answers, "anything else?") until the person
    says they're done, goes quiet after a follow-up, or 5 turns pass."""
    if voice is None or not busy.acquire(blocking=False):
        return
    try:
        speak(engine.greet())
        follow_up = False
        for _ in range(5):
            text = listen()
            if not text:
                if follow_up:  # silence after "anything else?" means done
                    break
                speak(engine._say("unclear"))
                continue
            t0 = time.time()
            reply = engine.handle(text)
            print(f"[timing] engine={time.time() - t0:.2f}s")
            if engine.last_intent in ("THANKS", "BYE"):
                speak(reply)
                break
            follow_up = not engine.pending  # a yes/no question is its own follow-up
            speak(reply + (" " + engine._say("anything_else") if follow_up else ""))
    except Exception as e:
        print("[conversation]", e)
        ring("error")
    finally:
        ring("idle")
        busy.release()


def load_voice():
    global voice
    try:
        from jarvis.voice import Voice
        t0 = time.time()
        voice = Voice(f"{DATA}/models")
        print(f"[voice] ready in {time.time() - t0:.1f}s")
    except Exception as e:
        print("[voice] disabled:", e)


ui = WebUI()
ui.expose_api("GET", "/api/state", lambda: state(engine))


def api_confirm(yes: int = 0):
    return {"reply": engine.confirm(bool(yes))}


def api_say(text: str = ""):
    reply = engine.handle(text)
    threading.Thread(target=speak, args=(reply,), daemon=True).start()
    return {"reply": reply}


def api_talk():
    threading.Thread(target=conversation, daemon=True).start()
    return {}


ui.expose_api("POST", "/api/confirm", api_confirm)
ui.expose_api("POST", "/api/say", api_say)
ui.expose_api("POST", "/api/talk", api_talk)

try:
    from arduino.app_bricks.keyword_spotting import KeywordSpotting
    wake = KeywordSpotting(confidence=0.8, debounce_sec=2.0)
    wake.on_detect(WAKE_WORD, lambda: threading.Thread(target=conversation, daemon=True).start())
    print(f"[wake] listening for {WAKE_WORD!r}")
except Exception as e:  # no microphone plugged in: dashboard still works
    print("[wake] disabled:", e)

threading.Thread(target=load_voice, daemon=True).start()
ring("idle")
App.run()
