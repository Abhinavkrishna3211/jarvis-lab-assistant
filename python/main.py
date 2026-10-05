"""JARVIS on the UNO Q (App Lab entry point).
Always listening: wake word -> greeting -> record the request -> whisper -> keyword rules, Gemma if they give up (one JSON action)
-> validate() -> laser / box LED -> Piper reply. Loans and returns wait for a spoken yes or a tap."""
import functools
import json
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
from jarvis.vision import Finder, hook_fit

DATA = "/app/data"
# Label inside the keyword model: "JARVIS" in our Edge Impulse model (app.yaml), "hey_arduino" in App Lab's built-in one.
WAKE_WORD = os.environ.get("JARVIS_WAKE_WORD", "JARVIS")

os.makedirs(DATA, exist_ok=True)
con = db.connect(f"{DATA}/jarvis.db")
db.seed(con)
hw = BridgeHardware()
# Gemma only sees requests the keyword rules can't handle; it takes ~28 s here, so say so first.
finder = Finder(DATA, lambda: grab(), f"{DATA}/jarvis-vision.eim")  # our Edge Impulse object-detection model
engine = Engine(con, HybridLLM(LlamaServerLLM(), on_slow=lambda: speak("One moment, sir. Running the calculations.")), hw,
                finder=finder)
engine.defer_laser = True  # the laser lights with the spoken reply (speak), not while it is being synthesised
voice = None  # loaded in the background: first start downloads ~136 MB of speech models
busy = threading.Lock()


def ring(s):
    try:
        hw.ring_state(s)
    except Exception as e:  # a missing MCU must not stop the conversation
        print("[bridge]", e)


def frames(cam, n):
    """n frames after the camera's exposure settles (the first few are dark)."""
    out = []
    while len(out) < n:
        f = cam.capture()
        if f is not None:
            out.append(f)
        time.sleep(0.05)
    return out


def grab():
    from arduino.app_peripherals.camera import Camera
    with Camera(0) as cam:
        return frames(cam, 8)[-1]


def calibrate():
    """Hang every tool on its own hook, then call this: where the camera sees each tool is fitted against the
    hook angles measured by hand. No laser needed (the camera never saw the laser dot on the white board)."""
    home = {r["name"]: (r["servo_pan"], r["servo_tilt"]) for r in con.execute(
        "SELECT items.name, servo_pan, servo_tilt FROM items JOIN locations ON items.location = locations.id "
        "WHERE locations.type = 'hook' AND servo_pan IS NOT NULL AND servo_tilt IS NOT NULL")}
    seen = finder.model().detect(grab())
    try:
        cal = hook_fit(seen, home)
    except ValueError as e:
        return {"error": str(e), "seen": seen}
    with open(f"{DATA}/vision.json", "w") as f:
        json.dump(cal, f)
    return dict(cal, seen=seen)


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


speaking = threading.Lock()  # dashboard /api/say and the voice loop must not talk over each other
spoke_at = 0.0  # when the last reply finished: a wake word right after it is our own voice (BT lags ~1 s)


@functools.lru_cache(maxsize=128)  # greetings and stock lines play at once instead of after a 2-3 s synth
def synth(text):
    return voice.synth(text)[0]


def sentences(text):
    return [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]


def laser(on):
    try:
        hw.laser(on, 10 if on else 0)  # still capped at 10 s in hardware.py and the sketch
    except Exception as e:
        print("[bridge]", e)


def speak(text, aim=False):
    """Sentence by sentence: the next one is synthesised while this one plays, and each sentence is
    cached, so "Anything else?" and other stock lines cost nothing after the first time.
    aim: the engine pointed at a tool; the laser is lit from the first word to the end of the reply."""
    print("JARVIS>", text)
    if voice is None:
        if aim:
            laser(True)
        return
    try:
        with speaking, open_speaker() as sp:  # open first: no speaker -> skip the ~2 s synth, mic opens at once
            t0 = time.time()
            parts = sentences(text)
            nxt = [None]
            def ahead(i):
                nxt[0] = synth(parts[i])
            audio = synth(parts[0])
            t = time.time() - t0  # wait before the first word
            ring("speaking")
            if aim:
                laser(True)
            total = 0
            for i in range(len(parts)):
                th = threading.Thread(target=ahead, args=(i + 1,)) if i + 1 < len(parts) else None
                if th:
                    th.start()
                sp.play_pcm(audio)
                total += len(audio)
                if th:
                    th.join()
                    audio = nxt[0]
            time.sleep(0.5)  # play_pcm returns ~0.2 s early and BT adds latency: let the tail finish before the mic opens
        print(f"[timing] tts={t:.2f}s audio={total / voice.tts_rate:.1f}s")
    except Exception as e:
        print("[speaker]", e)
    finally:
        global spoke_at
        spoke_at = time.time()
        if aim:
            laser(False)


def listen():
    from arduino.app_peripherals.microphone import Microphone
    ring("listening")
    from jarvis.voice import until_quiet
    t0 = time.time()
    with Microphone(device=0) as mic:  # device 0 = shared with the wake-word brick
        pcm = until_quiet(mic.stream(), mic.sample_rate)
    rec = time.time() - t0
    ring("thinking")
    text, t = voice.transcribe(pcm)
    if text:  # words were heard: fill the gap while the reply is worked out and synthesised (not on noise)
        threading.Thread(target=speak, args=(engine._say("filler"),), daemon=True).start()
    print(f"[timing] rec={rec:.1f}s stt={t:.2f}s peak={int(abs(pcm).max())} heard={text!r}")  # peak: 0..32767, near 0 = silence
    return text


def conversation():
    """One wake-up: greet, then keep going (requests, yes/no answers, "anything else?") until the person
    says they're done, goes quiet after a follow-up, or 5 turns pass."""
    print(f"[wake] {time.strftime('%T')}")  # compare with the greeting's "Starting speaker" time
    if speaking.locked() or time.time() - spoke_at < 1.5:  # our own voice through the speaker, not a person
        print("[wake] ignored: JARVIS was talking")
        return
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
            # a question of ours ("shall I log it?", "what's the job?", "say it again?") is its own follow-up
            follow_up = not (engine.pending or engine.asking_task or engine.last_intent in ("UNKNOWN", "WAKE"))
            speak(reply + (" " + engine._say("anything_else") if follow_up else ""), engine.take_laser())
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
        from jarvis.dialogue import BANK
        t0 = time.time()
        for part in ("morning", "afternoon", "evening"):  # every greeting, so a wake-up never waits for synth
            for line in BANK["wake"]:
                for s in sentences(line.format(part=part, name=engine.coordinator)):
                    synth(s)
        for key in ("filler", "anything_else", "unclear", "ask_task", "ready"):
            for line in BANK[key]:
                for s in sentences(line):
                    synth(s)
        synth("One moment, sir.")
        synth("Running the calculations.")
        print(f"[voice] greetings cached in {time.time() - t0:.1f}s")
    except Exception as e:
        print("[voice] disabled:", e)


ui = WebUI()
ui.expose_api("GET", "/api/state", lambda: state(engine))


def api_confirm(yes: int = 0):
    return {"reply": engine.confirm(bool(yes))}


def api_say(text: str = ""):
    reply = engine.handle(text)
    threading.Thread(target=speak, args=(reply, engine.take_laser()), daemon=True).start()
    return {"reply": reply}


def api_talk():
    threading.Thread(target=conversation, daemon=True).start()
    return {}


def api_point(pan: int = 90, tilt: int = 90, laser: int = 0):
    """Jog the head to find a hook's angles. laser=1 lights the dot (still off after 10 s)."""
    hw.point(pan, tilt)
    if laser:
        hw.laser(True, 10)
    return {"pan": pan, "tilt": tilt}


def api_snap():
    import cv2
    cv2.imwrite(f"{DATA}/wall.jpg", grab())
    return {"saved": f"{DATA}/wall.jpg"}


def api_calibrate():
    return calibrate()


ui.expose_api("POST", "/api/confirm", api_confirm)
ui.expose_api("POST", "/api/point", api_point)
ui.expose_api("POST", "/api/snap", api_snap)
ui.expose_api("POST", "/api/calibrate", api_calibrate)
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
