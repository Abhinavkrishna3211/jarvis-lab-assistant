# Project guide for contributors and coding agents

JARVIS is an offline voice assistant on an Arduino UNO Q for an IoT-club lab (DEV Hacktoberfest 2026,
"Build for a Friend"). Deadline: Mon 5 Oct 2026, 12:29 PM IST. Read `README.md` first.

## Commands
- Tests: `python -m pytest -q` (must stay green; CI runs them)
- Baseline eval: `python eval/run_eval.py`; with the model: `--gemma http://llamacpp-models-runner:9999/v1`
- Simulator: `python python/jarvis/app.py`
- App Lab layout: `app.yaml`, `python/main.py` (entry), `python/jarvis/` (package), `assets/`, `sketch/`.
- Log every measurement in `docs/measurements.md` and every build step in `docs/tutorial.md`.

## Rules the design depends on
- The model only returns one JSON action. Everything else (item checks, quantities, dates, stock,
  overdue) is done in code. Never let model output reach the database or hardware without `validate()`.
- Loans and returns always need a spoken "yes" or a dashboard tap before saving.
- Laser: 1 mW or less, auto-off 10 s, enforced in `hardware.py` and `sketch/sketch.ino`. Do not relax.
- Stay offline: no cloud calls at runtime. Stdlib only on the Linux side where possible.
- Commit messages: plain and descriptive, no co-author trailers.

## Status
Done and tested off-board: matcher, validator, dates, SQLite loans, persona, engine, dashboard, hybrid parser
(keyword rules first, Gemma only when they give up on a known item), 25 tests, 60-command evaluation set
(keyword baseline 41/60, hybrid 45/60 on the board).
Done on the UNO Q 2GB (bench, no peripherals): app import and start as `JARVIS`, Gemma 3 1B installed and served
by the App Lab runner (about 28 s per request), typed Gemma evaluation, sketch compiled (library versions pinned in `sketch/sketch.yaml`) and flashed, all four
Bridge calls answered (about 7 ms). See `docs/measurements.md`.
Not yet run on real parts: servos, laser off-timer with a real laser, LED strip, ring, mic, speaker, wake word.

## Remaining work, in order
1. Wire the servos, laser, strip and ring; verify the laser auto-off with a real laser; measure pointing error.
2. Audio: USB mic and speaker; measure per-stage latency with real speech. Put `arduino:keyword_spotting`
   back in the board's `app.yaml` (it was removed there only, because the app won't start without a mic).
3. Wake word: record "Hey Jarvis" with many voices plus lab noise, train in Edge Impulse, add
   `models/hey-jarvis.eim` (until then the app uses "Hey Arduino" or push-to-talk).
4. Real inventory: replace the placeholder items and hook angles in `jarvis/db.py` with the lab's data.
5. Record 60 spoken commands; report the hybrid vs the baseline, latency and false wakes.
6. Cut order if short on time: camera tool-wall check, touchscreen, tool-for-task, witty extras.
