# JARVIS: an offline lab assistant on the Arduino UNO Q

A voice assistant for an open IoT-club lab. Ask it where a tool is and a laser marks the hook; ask for a
component and the LED under its box lights; lend and return hardware by voice and it keeps the log.
Everything runs on the board: no internet, no cloud account.

> Built for the DEV Hacktoberfest 2026 Weekend Challenge, *Build for a Friend*.

## How it works

```
mic -> "Hey Jarvis" (App Lab keyword spotting, always listening) -> "Good evening, sir."
    -> record 5 s -> whisper.cpp tiny.en -> fuzzy candidate match (about 10 items)
    -> keyword rules; if they give up on a known item, Gemma 3 1B (App Lab llama.cpp runner,
       JSON-schema constrained) -> validator -> SQLite
    -> Piper reply and Bridge calls to the STM32: point / laser / box_led / ring_state
```

The model never touches facts it could invent. It returns one short JSON action; code checks the intent, the
item against the inventory, quantity, borrower and due date, and does all date and stock arithmetic.
Loans and returns are read back and need a spoken "yes" or a tap on the dashboard before anything is saved.

Why keyword rules first: on the UNO Q, Gemma 3 1B takes about 28 s per request and scored lower than the
rules on our 60 test commands (it also invents items when someone makes small talk). So the rules answer
instantly, and Gemma only gets the requests they can't parse but that mention an item or a use of one.
JARVIS says "One moment, sir" before those. The numbers are in [docs/measurements.md](docs/measurements.md).

| Layer | Where | Files |
|---|---|---|
| Intent parsing | Linux (MPU) | `python/jarvis/llm.py`, `python/jarvis/matcher.py` |
| Validation, dates, loans | Linux | `python/jarvis/validate.py`, `python/jarvis/dates.py`, `python/jarvis/db.py` |
| Dialogue / persona | Linux | `python/jarvis/dialogue.py`, `python/jarvis/engine.py` |
| Voice I/O | Linux | `python/jarvis/voice.py` |
| Laser, LEDs, servos | STM32 (MCU) | `sketch/sketch.ino` |
| Dashboard | Linux | `assets/index.html`, `python/jarvis/dashboard.py` |
| App Lab entry point | Linux | `python/main.py`, `app.yaml` |

## Try it without hardware

```bash
pip install -r requirements-dev.txt
python -m pytest -q              # parsing, validation and loan-logic tests
python eval/run_eval.py          # 60-command keyword baseline
python python/jarvis/app.py      # typed input, simulated hardware, dashboard on http://127.0.0.1:8000
```

The simulator uses the keyword rules alone unless you pass `--llm-url` pointing at any OpenAI-compatible
server running Gemma 3 1B; then it uses the same rules-then-Gemma parser as the board.

## Install on an Arduino UNO Q

JARVIS is a standard Arduino App Lab app. Full step-by-step instructions, including wiring, are in
[docs/tutorial.md](docs/tutorial.md). The short version:

1. Download this repository as a zip.
2. In App Lab: **My Apps → Import**, pick the zip. (Or on the board:
   `arduino-app-cli app import jarvis.zip`.)
3. Open the app. In the **Large Language Model** brick, make sure **Gemma 3 1B** is selected and
   downloaded (722 MB).
4. Plug a USB mic and speaker into a powered USB-C hub, then press **Run**. The first start downloads
   the whisper and Piper models (136 MB). After that it runs offline.
5. Say **"Hey Arduino"**. This is App Lab's built-in wake word, used until a custom "Hey Jarvis" model is trained.
   The dashboard is at `http://<board-ip>:7000`.

Hook angles and LED indexes in `python/jarvis/db.py` are placeholders until you calibrate in the real lab
(`docs/wiring.md`).

## Safety and privacy

- Laser: 1 mW or less, auto-off after 10 s (enforced in both Python and firmware), aimed only at the wall.
- Camera (stretch goal) faces the tool wall and boxes, never people.
- The loan log stores first names only and never leaves the board.

## Evaluation

`eval/commands.json` holds 60 labelled requests. `eval/run_eval.py` scores the keyword baseline, and with
`--gemma <url>` the Gemma pipeline, counting a request correct only if intent, item, quantity and borrower all
match after validation. On the UNO Q, with typed input:

| Parser | Correct | Time per command |
|---|---|---|
| Keyword rules | 41/60 | median 0.23 s |
| Gemma 3 1B alone | 21–22/60 | median about 28 s |
| **Hybrid (what JARVIS uses)** | **45/60** | median 0.35 s; Gemma asked on 18 of 60 |

We chose the hybrid rule after seeing Gemma's answers on these same 60 commands, so its score is optimistic.
Spoken tests with real people are still to do. All measured numbers, and how each was measured, are in
[docs/measurements.md](docs/measurements.md).

## License

MIT
