"""JARVIS on the UNO Q (App Lab entry point).
Always listening: wake word -> greeting -> record the request -> whisper -> keyword rules, Gemma if they give up (one JSON action)
-> validate() -> laser / box LED -> Piper reply. Loans and returns wait for a spoken yes or a tap."""
import os
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
engine = Engine(con, HybridLLM(LlamaServerLLM(), on_slow=lambda: speak("One moment, sir. Let me think.")), hw)
voice = None  # loaded in the background: first start downloads ~136 MB of speech models
busy = threading.Lock()


def ring(s):
    try:
        hw.ring_state(s)
    except Exception as e:  # a missing MCU must not stop the conversation
        print("[bridge]", e)


def speak(text):
    print("JARVIS>", text)
    if voice is None:
        return
    from arduino.app_peripherals.speaker import Speaker
    audio, t = voice.synth(text)
    ring("speaking")
    try:
        with Speaker(sample_rate=voice.tts_rate) as sp:
            sp.play_pcm(audio)
    except Exception as e:
        print("[speaker]", e)
    print(f"[timing] tts={t:.2f}s audio={len(audio) / voice.tts_rate:.1f}s")


def listen():
    from arduino.app_peripherals.microphone import Microphone
    ring("listening")
    with Microphone(device=0) as mic:  # device 0 = shared with the wake-word brick
        pcm = mic.record_pcm(LISTEN_SECONDS)
    ring("thinking")
    text, t = voice.transcribe(pcm)
    print(f"[timing] stt={t:.2f}s heard={text!r}")
    return text


def conversation():
    """One wake-up: greet, take a request, act, and follow through on a yes/no if it asked one."""
    if voice is None or not busy.acquire(blocking=False):
        return
    try:
        speak(engine.greet())
        for _ in range(3):  # request, then up to two yes/no answers
            text = listen()
            if not text:
                speak(engine._say("unclear"))
                continue
            t0 = time.time()
            reply = engine.handle(text)
            print(f"[timing] engine={time.time() - t0:.2f}s")
            speak(reply)
            if not engine.pending:
                break
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
