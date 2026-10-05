# Wiring and calibration

| Part | Connects to | Notes |
|---|---|---|
| Pan servo (SG90, bottom of the pan-tilt head) | STM32 PWM pin D5 | Swings left and right; detached after each move to stop jitter |
| Laser module (from a keychain pointer, cells removed) | D7 through a logic-level MOSFET (IRLZ44N): 270 R gate, 10k gate pulldown | 5 V rail through a 150 R series resistor, about 19 mA; firmware off-timer of 10 s |
| Tilt servo (SG90, top of the head, carries the laser) | D6 | Swings up and down (lower angle = higher dot) |
| WS2812 strip (one LED per box) | D8 through a 74AHCT125 (5 V) and 330 R | 8 LEDs by default |
| NeoPixel ring (status) | D9 through the same 74AHCT125 and 330 R | 16 LEDs |
| Servos, LEDs power | Separate 5 V supply | Shared ground with the UNO Q |
| Mic, speaker | USB sound card on a powered USB-C hub | Hub also feeds the USB camera |

Full schematic with the resistor calculations: [schematic/jarvis.pdf](schematic/jarvis.pdf) (KiCad source `schematic/jarvis.kicad_sch`, regenerate with `python docs/schematic/make_sch.py docs/schematic/jarvis.kicad_sch`).

Pins are set at the top of `sketch/sketch.ino`. Servo 1.3.0 and Adafruit NeoPixel 1.15.5 compile on the
`arduino:zephyr` 1.0.0 core (verified 4 Oct 2026; versions pinned in `sketch/sketch.yaml`).

## Pan-tilt head

A standard two-SG90 pan-tilt bracket (the two-piece plastic kit).

1. Before fitting the horns, centre both servos: `POST /api/point?pan=90&tilt=90` (laser stays off).
2. Pan servo in the base, horn up; the lower bracket screws onto that horn.
3. Tilt servo in the upper bracket; the laser module sits on the tilt platform, beam parallel to it,
   held with a zip tie or hot glue so it can't slip (a slipped laser silently breaks the calibration).
4. Mount the head at bench height facing the tool wall, with no walkway between head and wall. The beam
   should only ever reach the wall, never head height.
5. Fix the camera next to the head, not on it, so the camera's view and the head don't move together.
   Moving either one means calibrating again.
6. Servo power comes from the separate 5 V supply (about 0.7 A stall each), never from the UNO Q's 5 V pin.

## Calibrating hooks

Two steps, both from the dashboard host (`http://<board-ip>:7000`):

1. **Hook angles by hand.** For each hook, jog until the dot sits on it:
   `POST /api/point?pan=90&tilt=65&laser=1` (the laser still switches off after 10 s). Write each
   hook's `(pan, tilt)` into `HOOK_ANGLES` in `python/jarvis/db.py` and restart the app. Record the miss
   distance in centimetres for the evaluation.
2. **Camera fit.** Hang every tool on its own hook, then `POST /api/calibrate`. The camera finds each tool
   with the vision model and fits pixel position to `(pan, tilt)`; the result is saved to `data/vision.json`.
   It needs 2 or more tools seen. Hooks in one column only teach tilt; hooks spread across the wall teach
   both axes. Every aim is clamped to the box the calibrated hooks span, so a bad detection can't swing
   the laser off the wall.

Without `vision.json` (or with the camera unplugged), JARVIS points at each tool's home hook.
