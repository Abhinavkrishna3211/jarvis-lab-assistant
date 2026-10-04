# Measurements

Every number here comes from a real run on the bench. Each entry says what was measured, how, and
whether the input was typed, spoken by a person, or synthesized. If something didn't work, it stays in.

## Test bench

| | |
|---|---|
| Board | Arduino UNO Q, 2 GB RAM (Qualcomm QRB2210, 4 × Cortex-A53 @ 2.0 GHz per spec; STM32U585 MCU) |
| OS | Debian, kernel 6.16.7; Arduino App Lab CLI and daemon 0.13.0 |
| Python runtime | App Lab container `python-apps-base:0.12.0`, Python 3.13 |
| Memory at idle | 1740 MB total, 1249–1277 MB available (`free -m`, App Lab running, desktop on) |
| Disk | 9.8 GB root, 90% used before cleanup, 62% after, 70% with Gemma installed (`df -h /`) |
| Network | Wi-Fi, 34–49% signal on 2.4 GHz at the bench |

## 1. Firmware compiles on the UNO Q core (4 Oct 2026)

**What:** does `sketch/sketch.ino` (servo, laser timer, NeoPixel strip and ring, four Bridge calls)
build for the UNO Q's Zephyr-based core with the libraries pinned in `sketch/sketch.yaml`?

**How:** on the board, `arduino-cli compile --fqbn arduino:zephyr:unoq --profile default sketch`.
Nothing was flashed.

**Result:** builds. 102,288 bytes of 786,432 flash (13%), 41,280 bytes of 262,144 RAM (15%).

**Rebuilt after the ring fix (section 6), same command:** 101,716 bytes flash (12%), 40,940 bytes RAM
(15%), 1 min 28 s to compile on the board.

**Gotcha:** the first build failed with `Arduino_RPClite.h: No such file`. Sketch profiles don't
pull library dependencies automatically, so every dependency of Arduino_RouterBridge has to be listed.

## 2. Speech-to-text and text-to-speech on the UNO Q CPU (4 Oct 2026)

**Why these engines:** App Lab's own speech blocks (`arduino:asr`, `arduino:tts`) only run on the
VENTUNO Q. On the UNO Q we use whisper.cpp (`pywhispercpp` 1.5.1) and Piper (`piper-tts` 1.8.0).
Both install as prebuilt ARM wheels inside the App Lab container, with nothing to compile.

**How:** a throwaway App Lab container on the board. Piper speaks a sentence, the audio is resampled
from 22,050 Hz to 16 kHz, and whisper transcribes it. Timings use `time.time()` around each call,
after one warm-up call. **The input is synthesized speech (Piper's northern English male voice),
not a person.** Piper's pronunciation of "ESP32s" is itself poor, so treat accuracy as a lower bound
on the pipeline, not a measure of how it does with real students.

### Text to speech (Piper `en_GB-northern_english_male-medium`)

| Sentence | Audio length | Time to synthesize |
|---|---|---|
| "Good evening, sir. What do you need?" | 2.0 s | 1.00 s |
| "Where is the wire stripper" | 1.4 s | 0.74 s |
| "Lend two ESP32s to Arjun till Friday" | 2.7 s | 1.42 s |

That's about 0.5 s of work per second of speech, so Piper is not the bottleneck.

### Speech to text (whisper tiny.en): four settings tried

| Setting | Time per command | "wire stripper" | "Lend two ESP32s to Arjun till Friday" | "What is overdue" |
|---|---|---|---|---|
| tiny.en, defaults (30 s window) | 4.8–7.0 s | "Y stripper" | "Len Tujas Betha he twos to Arjantil Friday." | "What is over to you?" |
| + hint list of items/names | 5.3–5.5 s | correct | garbled | "What is over to you?" |
| + hint list + `audio_ctx=512` | 1.7–3.1 s | "Y stripper" | garbled | "What is over to you?" |
| base.en + hint list + `audio_ctx=512` | 3.8–4.1 s | correct | garbled | correct |
| **tiny.en + `audio_ctx=512` (chosen)** | **1.40–2.33 s** | "Y stripper" | "lent to the SB 32 to Argentina till Friday." | "What is over to you?" |
| tiny.en + `audio_ctx=768` | 2.18–2.27 s | same as 512 | same as 512 | same as 512 |

**What we learned:**
- whisper pads every clip to a 30 s window by default. `audio_ctx=512` shrinks that to about 10 s
  and cuts the time by a factor of 3.4 (4.8 s → 1.4 s) with the same transcripts. Our recordings are
  5 s, so nothing gets cut off.
- **The hint list is harmful.** On a short clip, whisper output the hint itself
  ("Arjun returned the multimeter" came back as "Arjun, Meera."). We dropped it.
- base.en is more accurate ("overdue", "wire stripper") but 2.7 times slower. We'll decide between tiny
  and base once we have recordings of real voices.

**Memory:** Piper + whisper tiny.en loaded together peaked at 381 MB RSS.
**Disk:** whisper tiny.en model 75 MB, Piper voice 61 MB. Both are downloaded once on first start.

## 3. Installing and starting the app on the board (4 Oct 2026)

**How:** board cleaned first (two old apps exported to zips and deleted, three unused Docker images
removed): disk went from 90% to 62% used. Then `arduino-app-cli app import`, the model download, and
`arduino-app-cli app start user:jarvis`, timed with `time`.

| Step | Result |
|---|---|
| Gemma 3 1B download (722 MB, through the App Lab daemon) | 7 min 37 s on our Wi-Fi (about 1.6 MB/s); disk 62% → 70% |
| First `app start`: compile and flash the sketch | about 2 min 14 s |
| First `app start`: pull llama.cpp runner image, create containers | 52.6 s |
| First run: install `pywhispercpp` + `piper-tts`, download speech models | about 1 min |
| Dashboard reachable at `http://<board-ip>:7000` | yes |

**What went wrong, and what it tells you:**
- **The first download attempt killed the Wi-Fi.** The board was at 34% signal. About 45 s into the
  722 MB download the link timed out and NetworkManager never reconnected, so the board needed a
  power cycle. At 42–49% signal the retry finished. Put the board near the router for the first start.
- **The app won't start without a microphone** if `app.yaml` declares the wake-word brick
  (`[ERROR] No Microphone Device Found`). Our bench has no mic yet, so for these measurements the
  brick was removed from the board's copy of `app.yaml` only. Even then, the app's wake-word setup
  retried the missing service for 2 min 14 s before falling back to the dashboard Talk button.
- One start failed on a DNS lookup for `ghcr.io` right after a Wi-Fi reconnect. Retrying worked.

## 4. Gemma 3 1B speed on the UNO Q (4 Oct 2026)

**How:** a script inside the app container sends JARVIS's real prompt (instructions + up to 10
candidate items + the request, 185–214 tokens) to App Lab's llama.cpp runner, exactly as the app
does, and records wall time plus llama.cpp's own `timings`. **Input is typed text.** One cold
request, then six different requests. Memory sampled every 3 s with `docker stats` and `free -m`.
Runner settings come from App Lab: 4 threads, context 16,384, batch 512.

| | Result |
|---|---|
| Reading the prompt | 9.3–10.4 tokens/s |
| Generating the reply | 4.7–5.1 tokens/s (one run: 2.5) |
| Time per command, warm | **26.6–35.2 s** (prompt about 21 s, reply of 37–58 tokens about 8 s) |
| First command after start (model load) | 46.6 s |
| Memory, llama.cpp runner | up to 869 MB |
| Memory, JARVIS app with whisper + Piper loaded | up to 233 MB |
| Lowest `available` memory during the run | 721 MB of 1740 MB |
| CPU clock during the run | 1.61 GHz on all four cores (`scaling_cur_freq`), 53 °C |

**What we learned:**
- **Memory is fine; speed is the problem.** Everything fits in 2 GB with about 700 MB to spare, but
  about 30 s per command is far too slow to talk to.
- **The fixed part of the prompt isn't reused.** Sending the same request twice still processed all
  211 tokens, even with `cache_prompt` set. App Lab runs llama.cpp in its experimental router mode.
- **Our 30 s client timeout was shorter than a real request.** Raised to 90 s.
- Gemma's replies were often wrong on this sample: "lend two ESP32s to Arjun till Friday" and
  "Meera returned the soldering iron" both came back as `FIND_TOOL`, and it filled in fields that
  don't apply (`"due": "in 3 days"` on a tool search). The validator throws those extra fields away,
  but the wrong intent gets through. Section 5 has the full 60-command comparison.

## 5. Gemma vs the keyword baseline, 60 typed commands (4 Oct 2026)

**How:** `eval/run_eval.py --gemma http://llamacpp-models-runner:9999/v1`, run inside the app
container on the board. **Typed input.** Both parsers go through the same validator, and a command
counts as correct only if intent, item, quantity and borrower all match what the system would act on.
Gemma uses the prompt in `python/jarvis/llm.py` as of this date (zero-shot, JSON-schema constrained,
temperature 0). Raw results: one row per command, saved by `--json`.

| Intent | Commands | Keyword baseline | Gemma 3 1B |
|---|---|---|---|
| FIND_TOOL | 9 | 5 | **9** |
| FIND_COMPONENT | 8 | 6 | **8** |
| TOOL_FOR_TASK | 8 | 0 | 0 |
| LEND | 8 | **4** | 0 |
| RETURN | 6 | **6** | 0 |
| WHO_HAS | 5 | **4** | 0 |
| STOCK | 4 | **4** | 0 |
| OVERDUE | 4 | **4** | 1 |
| UNKNOWN (off-topic) | 8 | **7** | 4 |
| **Total** | **60** | **40** | **22** |

Per command: both right 15, keyword only 25, Gemma only 7, neither 13.

**What we learned:**
- **Gemma loses, 22 to 40.** It is better at one thing, recognising an item from loose wording ("i
  can't find the glue gun", "got any ultrasonic sensors"), and that accounts for all 7 commands
  only Gemma got right.
- **It labels almost everything as a search.** Every loan, return, stock and who-has question came
  back as `FIND_TOOL` or `FIND_COMPONENT`, usually with the right item. With this prompt, the 1B
  model picks up the item but not the intent.
- **Tool-for-task: right tool, wrong label.** For 6 of 8 "what do I use to…" questions Gemma named
  the right tool (side cutters for zip ties, multimeter for continuity) but labelled it `FIND_TOOL`,
  so the scorer counts it wrong. JARVIS would still point at the right hook. The keyword baseline
  named none of them. We report this separately rather than re-score.
- **It makes things up for off-topic requests.** "What's the weather", "play some music" → the
  multimeter; "thanks jarvis" → the ultrasonic sensor. The validator can't catch these because the
  item is real. The keyword baseline correctly said it didn't understand.
- **What-if, computed from the same recorded answers:** keyword parser first, Gemma only when the
  keyword parser gives up, would score 41/60 and call Gemma on 25 of 60 commands.
- **Timing:** a stray second copy of the evaluation shared the model for the first 34 commands, so
  only the last 26 timings are clean: **23.1–32.5 s, median 28.0 s**, matching section 4.

## 7. Second run, and the hybrid parser JARVIS now uses (4 Oct 2026)

Because of section 5, `python/jarvis/llm.py` now has `HybridLLM`: the keyword rules answer first, and Gemma
is asked only when the rules return UNKNOWN **and** the request names an item or a known use of one
(matcher score 0.7 or more). JARVIS says "One moment, sir. Let me think." before a Gemma call.

**Be aware:** we chose this rule after seeing section 5's answers, on the same 60 commands, so the hybrid
score below is optimistic. A fresh set of commands would be a fairer test.

**How:** same as section 5, a clean single run, typed input, board otherwise idle. Then the matcher bug
below was fixed and the keyword and hybrid parts were run again (`eval_v3`).

| Intent | Commands | Keyword (old matcher) | Gemma 3 1B (2nd run) | Keyword (fixed matcher) | **Hybrid (fixed matcher)** |
|---|---|---|---|---|---|
| FIND_TOOL | 9 | 5 | 9 | 5 | 8 |
| FIND_COMPONENT | 8 | 6 | 8 | 6 | 8 |
| TOOL_FOR_TASK | 8 | 0 | 0 | 0 | 0 |
| LEND | 8 | 4 | 0 | 4 | 4 |
| RETURN | 6 | 6 | 0 | 6 | 6 |
| WHO_HAS | 5 | 4 | 0 | 4 | 4 |
| STOCK | 4 | 4 | 0 | 4 | 4 |
| OVERDUE | 4 | 4 | 1 | 4 | 4 |
| UNKNOWN (off-topic) | 8 | 7 | 3 | 8 | 7 |
| **Total** | **60** | **40** | **21** | **41** | **45** |
| Time per command | | median 0.23 s | median 28.8 s (max 37.6) | median 0.23 s | **median 0.35 s, mean 8.5 s, max 33.4 s** |

The hybrid called Gemma on 18 of 60 commands.

**What we learned:**
- **Gemma isn't fully repeatable at temperature 0.** The second run gave a different answer on 2 of 60
  commands (21 instead of 22). "how do i program a pico" went from UNKNOWN to "soldering iron".
- **Matcher bug found and fixed.** Three-letter aliases ("esp", "uno") fuzzy-matched any two-letter
  fragment at 0.76: the "es" in "yes", the "un" in "Arjun". So "lend a teleporter to Arjun till Friday"
  became an ESP32 loan (still behind the spoken yes), and a stray "yes" was sent to Gemma. Short aliases
  now have to match exactly. Keyword baseline 40 → 41; regression test added.
- **When Gemma is wrong in the hybrid, it's mostly harmless.** Of the 13 hybrid misses that went to
  Gemma, 12 came back as a search (`FIND_TOOL`/`FIND_COMPONENT`), and 6 of those name the right tool for a
  "what do I use to…" question, so the laser would still mark the right hook. None became a loan or
  a return. The worst is "how do i program a pico", which points at the soldering iron.
- **Still not solved:** loans phrased without "lend/give/loan" ("Rahul needs three servos until
  Monday", "Nikhil is taking the soldering iron") get treated as searches.

## 8. Full voice pipeline on the board, synthesized speech (4 Oct 2026)

**How:** `bench_pipeline.py` inside the app container. **Synthesized input:** Piper speaks the request,
it's resampled to 16 kHz and padded to the app's 5 s recording, then whisper tiny.en → engine
(`HybridLLM` with the real Gemma, real `BridgeHardware` to the flashed sketch, fresh database) → Piper
speaks the reply. No mic or speaker; nothing wired to the pins. Second run, after the matcher fix.

| Said (by Piper) | Whisper heard | Path | Speech to text | Engine | Text to speech |
|---|---|---|---|---|---|
| where is the wire stripper | Where is the wire stripper? | rules | 1.59 s | 0.35 s (Bridge 45 ms) | 1.53 s |
| show me the tweezers | Show me the tweezers. | Gemma | 1.55 s | 66.3 s * | 1.79 s |
| lend two ESP32s to Arjun till Friday | Learn to USB for E2s to Argentina till Friday. | Gemma | 6.97 s * | 57.4 s * | 1.45 s |
| yes (nothing pending) | Yes. | rules | 2.08 s | 0.02 s | 1.81 s |
| what's the weather | What's the weather? | rules | 1.56 s | 0.12 s | 0.69 s |

Loading whisper and Piper takes 12.8 s at app start.

**Time from the end of a request to the start of the reply** (the 5 s recording comes first):
**about 3.5 s** when the rules handle it. When Gemma handles it, about 3.5 s plus the Gemma time, which is
24–34 s in sections 5 and 7.

\* **Why these are slow, and why we don't count them:** the benchmark loads its own whisper and Piper
next to the running app's copy, so the board held two sets of speech models. During the Gemma call:
570 MB available, `jarvis-main-1` 300 MB, `jarvis-llamacpp-models-runner-1` 479 MB (it had been 869 MB),
so the model weights were being pushed out of memory and re-read. In the first pipeline run, before the
matcher fix, the same Gemma calls took 31.6–39.6 s. The evaluation in section 7 ran in the same container
without loading speech models, which matches how the app really runs.

**Memory as the app really runs:** app with speech models loaded about 300 MB, Gemma runner 869 MB,
about 1.17 GB of 1.74 GB, which fits.

**What we learned:**
- Whisper tiny.en gets short, plain requests right, but it wrecked the loan sentence ("ESP32s to
  Arjun" → "USB for E2s to Argentina"). The first run heard "Lentivius B32s to Argentina Friday". This is
  Piper's voice, not a person; real spoken tests are still needed. Names and part numbers are the weak spot.
- Bridge calls inside a real command take 39–66 ms in total, since one command makes several calls.

## 6. Bridge calls from Linux to the sketch (4 Oct 2026)

**How:** inside the app container, `Bridge.call()` for each of `ring_state`, `box_led`, `point`,
`laser(False)`, 20 times each after one warm-up, timed with `time.perf_counter()`. Sketch flashed by
`app start`. Nothing is wired to the pins yet, so this measures the link, not the servos.

| Sketch version | Result |
|---|---|
| Status ring animated, redrawn every 40 ms | **every call timed out after 10 s** (two attempts) |
| Same sketch, ring redraw commented out | all four calls work: 5.9–7.9 ms |
| **Fixed: ring drawn once per state change, solid colour per state** | **6.2–8.2 ms** (median 6.9–7.6 ms) |

**What we learned:** the ring animation called `ring.show()` 25 times a second. Each call bit-bangs
the NeoPixel data and holds up the MCU, and the Bridge never got a reply out in time. The LED strip
under the boxes, which only redraws when asked, was never a problem. So the ring now shows a solid
colour per state (dim blue idle, bright blue listening, amber thinking, white speaking, red error),
drawn only when the state changes. The router log also shows `invalid packet, expected array`
right after every flash, with or without the fix; that's harmless noise while the MCU restarts.

**Not verified yet:** that the laser actually switches off after 10 s and that the servos reach their
angles. Both need the parts on the bench.

## Still to measure
- A fresh set of commands to test the hybrid rule fairly (section 7).
- Spoken commands from real people (needs a USB mic), wake word false wakes per hour and misses
  out of 50, laser pointing error (needs the servo and laser).
