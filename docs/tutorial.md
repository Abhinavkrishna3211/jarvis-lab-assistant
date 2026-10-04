# Build your own JARVIS: step by step

This guide takes you from an empty Arduino UNO Q to a lab assistant that answers to its wake word, marks
tools with a laser, and keeps the lending log by voice. The steps are the ones we actually followed; any
step not yet run on real hardware is marked **(not yet verified)**.

Numbers quoted here come from [measurements.md](measurements.md).

## What you need

| Part | Why | Status on our bench |
|---|---|---|
| Arduino UNO Q (2 GB is enough) | Runs everything: Linux for speech and the model, STM32 for the hardware | ✅ |
| Powered USB-C hub with USB-A ports | The UNO Q has one USB-C port; mic, speaker and power share it | to buy |
| USB microphone + USB speaker (or a USB sound card) | Voice in and out | to buy |
| SG90 servos × 2 (pan, tilt) | Aim the laser | 1 of 2 |
| Laser diode module, **1 mW or less**, plus a logic-level MOSFET (IRLZ44N) | Marks the hook on the tool wall | MOSFET ✅, laser to buy |
| WS2812 LED strip | One LED under each component box | to buy |
| 16-LED NeoPixel ring | Status: idle, listening, thinking, speaking, error | ✅ |
| Separate 5 V supply | Servos and LEDs draw too much for the board | |

You also need a computer with [Arduino App Lab](https://www.arduino.cc/en/software/) and an
internet connection **for the first start only** (to download the models).

## Step 1: Prepare the board

1. Connect the UNO Q to Wi-Fi through App Lab's first-run setup.
2. Check you have room. Open the board's terminal (App Lab, or `ssh arduino@<board-ip>`) and run:
   ```bash
   free -m      # we had 1249–1277 MB available out of 1740 MB
   df -h /      # we had 1.1 GB free out of 9.8 GB: too little
   ```
   JARVIS needs about 2.5 GB of free disk on the first start: the Gemma model (722 MB), the
   llama.cpp and keyword-spotting runner images, and the speech models (136 MB). If you're short, export
   any old apps you want to keep (`arduino-app-cli app export <app> backup.zip --include-data`), then delete
   them in App Lab and remove Docker images you no longer use (`docker images`, then `docker rmi <image>`).

## Step 2: Import the app

1. Download this repository as a zip (GitHub: **Code → Download ZIP**).
2. In App Lab, import the zip as a new app. You can do the same from the board's terminal:
   ```bash
   arduino-app-cli app import jarvis.zip
   ```
   Verified on our UNO Q 2GB.

What's inside, and why App Lab needs each piece:

| Path | Role |
|---|---|
| `app.yaml` | Declares the app and its three bricks: `arduino:llm` (Gemma 3 1B), `arduino:web_ui` (dashboard), `arduino:keyword_spotting` (wake word) |
| `python/main.py` | Entry point App Lab runs. Ends with `App.run()` |
| `python/jarvis/` | The assistant: matcher, validator, dates, loans database, persona, speech |
| `python/requirements.txt` | `pywhispercpp` and `piper-tts`, installed automatically by App Lab |
| `assets/index.html` | Dashboard, served on port 7000 |
| `sketch/` | STM32 firmware: servos, laser off-timer, LED strip and ring |

## Step 3: Choose the model

Open the app and click the **Large Language Model** brick. Select **Gemma 3 1B**
(`llamacpp:gemma-3-1b-it-Q4_0`, 722 MB) and download it. App Lab runs it in its own llama.cpp container.
Nothing has to be compiled. From the board's terminal the same install is:
```bash
curl -X PUT http://127.0.0.1:8800/v1/models/llamacpp:gemma-3-1b-it-Q4_0
```
The download took 7 min 37 s for us. Keep the board close to the router: ours dropped off Wi-Fi at 34%
signal halfway through and didn't reconnect until we power-cycled it.

Why Gemma 3 1B: it's the largest instruction-tuned model App Lab offers for the UNO Q, and JARVIS only
asks it for one short JSON action per request. The code checks everything it returns.

On the UNO Q it takes about 28 s per request, so JARVIS tries simple keyword rules first and only asks
Gemma when they give up on a request that mentions a known item. See
[measurements.md](measurements.md) for how it did.

## Step 4: Wire the hardware

See [wiring.md](wiring.md) for the pin table. In short: servos on D5/D6, laser through the MOSFET on D7,
LED strip on D8, status ring on D9, all powered from a separate 5 V supply with a shared ground.

**Laser safety:** use a module rated 1 mW or less. The firmware switches it off after 10 s no matter
what Python asks for, and Python caps the request at 10 s too. Mount the turret so it can only reach
the tool wall, never head height.

The firmware compiles as-is for the UNO Q: 12% of flash, 15% of RAM. App Lab flashes it when you press Run.

## Step 5: Run it

Plug in the USB mic first: App Lab refuses to start the app without one
("No Microphone Device Found"), because the wake-word brick needs it. Press **Run** in App Lab. On the first start, the app downloads the whisper tiny.en (75 MB) and Piper
voice (61 MB) models into the app's `data/` folder. That took 144 s on our Wi-Fi. After that, everything
works offline. The app starts on our board (tested without the wake-word brick, since our bench has no mic yet).
The status ring shows one solid colour per state: dim blue idle, bright blue listening, amber thinking,
white speaking, red error. It isn't animated, because constant redraws blocked the Bridge.

- Dashboard: `http://<board-ip>:7000`. Stock, open loans, tap-to-confirm, a text box, and a Talk button.
- Wake word: say **"Hey Arduino"** (App Lab's built-in model) until you train "Hey Jarvis" (Step 7).

## Step 6: Talk to it

```
You:    Hey Arduino
JARVIS: Good evening, sir. What do you need?
You:    Where's the wire stripper?
JARVIS: Marked. Do return the wire stripper to the same hook, sir.     (laser on the hook, off after 10 s)

You:    Hey Arduino
JARVIS: Good evening, sir. The lab is at your disposal.
You:    Lend two ESP32s to Arjun till Friday.
JARVIS: Lending 2 ESP32 to Arjun until Friday 9 October. Shall I log it?
You:    Yes.
JARVIS: Logged. I'll keep an eye on its return.
```

Nothing is saved until you say yes (or tap **Yes, log it** on the dashboard).

## Step 7: Train "Hey Jarvis" (not yet done)

Uses App Lab's Edge Impulse integration: record the wake word in many voices plus lab noise, train a
keyword model, install it from the Keyword Spotting brick's AI models tab, then set the environment
variable `JARVIS_WAKE_WORD=hey_jarvis`.

## Step 8: Your lab's inventory (not yet done)

Replace the placeholder items, hook angles and LED indexes in `python/jarvis/db.py`. To calibrate each hook,
jog the servos until the dot sits on it and store the angles.

## Try it on a laptop first

No board needed:
```bash
pip install -r requirements-dev.txt
python -m pytest -q
python python/jarvis/app.py
```
