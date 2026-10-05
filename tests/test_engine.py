from datetime import date

import pytest

from jarvis import db
from jarvis.engine import Engine
from jarvis.hardware import SimHardware
from jarvis.llm import HybridLLM, ScriptedLLM, keyword_parse
from jarvis.matcher import best_item, candidates, normalise, words_to_digits
from jarvis.dates import resolve_due
from jarvis.validate import Invalid, validate

TODAY = date(2026, 10, 4)  # a Sunday


@pytest.fixture
def con():
    c = db.connect()
    db.seed(c)
    return c


def make(con, table):
    hw = SimHardware()
    return Engine(con, ScriptedLLM(table), hw, today=TODAY), hw


def test_number_words():
    assert words_to_digits("give two esp thirty two") == "give 2 esp 32"
    assert normalise("ESP-32s") == "esp 32s"


def test_candidates_include_spoken_esp(con):
    names = [c["name"] for c in candidates("give two esp thirty twos to Arjun", db.all_items(con))]
    assert "ESP32" in names and len(names) <= 10


def test_short_aliases_need_an_exact_match(con):
    items = db.all_items(con)
    assert best_item("yes", items) is None                                     # was ESP32 via 'es'
    assert best_item("lend a teleporter to Arjun till Friday", items) is None  # was ESP32 / Uno
    assert best_item("give me an uno", items)["name"] == "Arduino Uno"


def test_candidates_by_use(con):
    names = [c["name"] for c in candidates("which thing cuts zip ties", db.all_items(con))]
    assert "side cutters" in names


def test_due_dates():
    assert resolve_due("Friday", TODAY) == "2026-10-09"
    assert resolve_due("sunday", TODAY) == "2026-10-11"  # never "today"
    assert resolve_due("tomorrow", TODAY) == "2026-10-05"
    assert resolve_due("in 3 days", TODAY) == "2026-10-07"
    assert resolve_due("whenever", TODAY) is None
    assert resolve_due("2020-01-01", TODAY) is None


@pytest.mark.parametrize("bad", [
    {"intent": "LEND", "item": "Teleporter", "qty": 1, "borrower": "Arjun", "due": "Friday"},
    {"intent": "LEND", "item": "ESP32", "qty": 500, "borrower": "Arjun", "due": "Friday"},
    {"intent": "LEND", "item": "ESP32", "qty": 2, "borrower": "Arjun; DROP", "due": "Friday"},
    {"intent": "LEND", "item": "ESP32", "qty": 2, "borrower": "Arjun", "due": "never"},
    {"intent": "UNKNOWN"}, {"intent": "EXPLODE"}, "garbage",
])
def test_validator_rejects(con, bad):
    with pytest.raises(Invalid):
        validate(bad, con, TODAY)


def test_find_tool_points_laser(con):
    e, hw = make(con, {"where's the wire stripper": {"intent": "FIND_TOOL", "item": "wire stripper"}})
    reply = e.handle("Where's the wire stripper")
    assert "wire stripper" in reply
    kinds = [c[0] for c in hw.calls]
    assert kinds == ["point", "laser"] and hw.calls[1][2] <= 10


def test_find_component_lights_box(con):
    e, hw = make(con, {"where are the esp32s": {"intent": "FIND_COMPONENT", "item": "ESP32"}})
    reply = e.handle("Where are the ESP32s")
    assert "10" in reply and hw.calls[0][:2] == ("box_led", 0)


def test_lend_needs_confirmation_then_logs(con):
    t = {"lend two esp32s to arjun till friday":
         {"intent": "LEND", "item": "ESP32", "qty": 2, "borrower": "arjun", "due": "Friday"}}
    e, _ = make(con, t)
    reply = e.handle("Lend two ESP32s to Arjun till Friday")
    assert "Arjun" in reply and "Friday 9 October" in reply
    assert db.open_loans(con) == []           # nothing saved before the yes
    e.handle("yes")
    loans = db.open_loans(con)
    assert len(loans) == 1 and loans[0]["qty"] == 2 and loans[0]["due_date"] == "2026-10-09"
    assert db.available(con, db.get_item(con, "ESP32")) == 8


def test_lend_cancelled(con):
    t = {"lend two esp32s to arjun till friday":
         {"intent": "LEND", "item": "ESP32", "qty": 2, "borrower": "Arjun", "due": "Friday"}}
    e, _ = make(con, t)
    e.handle("Lend two ESP32s to Arjun till Friday")
    e.handle("no")
    assert db.open_loans(con) == [] and e.pending is None


def test_double_confirm_logs_once(con):
    # spoken "yes" and a dashboard tap arriving together must not crash or log twice
    t = {"lend two esp32s to arjun till friday":
         {"intent": "LEND", "item": "ESP32", "qty": 2, "borrower": "Arjun", "due": "Friday"}}
    e, _ = make(con, t)
    e.handle("Lend two ESP32s to Arjun till Friday")
    e.handle("yes")
    assert e.confirm(True) == ""
    assert len(db.open_loans(con)) == 1


def test_return_restores_stock_and_overdue(con):
    esp = db.get_item(con, "ESP32")
    db.lend(con, esp, 2, "Arjun", "2026-10-01", date(2026, 9, 28))
    assert len(db.overdue(con, TODAY)) == 1
    t = {"arjun returned the esp32s": {"intent": "RETURN", "item": "ESP32", "qty": 2, "borrower": "Arjun"},
         "what's overdue": {"intent": "OVERDUE"}}
    e, _ = make(con, t)
    assert "overdue" in e.handle("What's overdue?").lower()
    e.handle("Arjun returned the ESP32s")
    e.handle("yes")
    assert db.overdue(con, TODAY) == [] and db.available(con, db.get_item(con, "ESP32")) == 10


def test_cannot_lend_more_than_stock(con):
    t = {"lend 99 esp32s to arjun till friday":
         {"intent": "LEND", "item": "ESP32", "qty": 99, "borrower": "Arjun", "due": "Friday"}}
    e, _ = make(con, t)
    reply = e.handle("Lend 99 ESP32s to Arjun till Friday")
    assert "10 ESP32" in reply
    assert e.pending is None


def test_unknown_item_never_bluffs(con):
    t = {"where is the flux capacitor": {"intent": "FIND_TOOL", "item": "flux capacitor"}}
    e, hw = make(con, t)
    reply = e.handle("Where is the flux capacitor")
    assert "don't have" in reply or "stock" in reply
    assert hw.calls == []


def test_llm_failure_is_survivable(con):
    class Boom:
        def parse(self, *a): raise ConnectionError
    hw = SimHardware()
    e = Engine(con, Boom(), hw, today=TODAY)
    assert "wrong" in e.handle("anything")
    assert hw.calls[-1] == ("ring_state", "error")


def test_who_has(con):
    db.lend(con, db.get_item(con, "multimeter"), 1, "Meera", "2026-10-09", TODAY)
    e, _ = make(con, {"who has the multimeter": {"intent": "WHO_HAS", "item": "multimeter"}})
    assert "Meera" in e.handle("Who has the multimeter")


def test_small_talk_is_answered_in_code(con):
    e, hw = make(con, {"thanks where is the multimeter": {"intent": "FIND_TOOL", "item": "multimeter"}})
    e.handle("Thank you.");            assert e.last_intent == "THANKS"
    e.handle("No, that's all.");       assert e.last_intent == "BYE"
    assert "JARVIS" in e.handle("Who are you?")
    assert hw.calls == []
    e.handle("thanks where is the multimeter")  # long enough to be a request, not small talk
    assert e.last_intent == "FIND_TOOL"


def test_asks_for_the_job_then_points_at_the_tool(con):
    hw = SimHardware()
    e = Engine(con, HybridLLM(ScriptedLLM({})), hw, today=TODAY)  # keyword rules, no model
    e.handle("I have this need.")
    assert e.asking_task and hw.calls == []
    assert "vernier" in e.handle("Measure the diameter of a pipe.") and hw.calls[0][0] == "point"
    assert not e.asking_task


def test_wake_greeting_matches_time_of_day(con):
    e, hw = make(con, {})
    assert "Good morning" in e.greet(hour=8)
    assert "Good evening" in e.greet(hour=21)
    assert hw.calls == []


def test_keyword_baseline_basics(con):
    items = db.all_items(con)
    assert keyword_parse("where is the wire stripper", items)["intent"] == "FIND_TOOL"
    assert keyword_parse("what's overdue", items)["intent"] == "OVERDUE"
    assert keyword_parse("lend two esp32s to Arjun till Friday", items)["borrower"] == "Arjun"
    assert keyword_parse("which tool should I use to measure diameter", items)["item"] == "vernier caliper"
    assert keyword_parse("I need a tool to check continuity", items)["item"] == "multimeter"


def test_hybrid_asks_gemma_only_when_rules_give_up_on_a_known_item(con):
    items, asked = db.all_items(con), []
    gemma = ScriptedLLM({"show me the tweezers": {"intent": "FIND_TOOL", "item": "tweezers"}})
    h = HybridLLM(gemma, on_slow=lambda: asked.append(1))
    ask = lambda t: h.parse(t, candidates(t, items))
    assert ask("where's the wire stripper")["intent"] == "FIND_TOOL" and not asked  # rules handle it
    assert ask("what's the weather")["intent"] == "UNKNOWN" and not asked          # small talk: no model
    assert ask("show me the tweezers")["item"] == "tweezers" and asked == [1]


def test_wake_word_is_stripped_before_parsing(con):
    e, hw = make(con, {"where is the multimeter": {"intent": "FIND_TOOL", "item": "multimeter"}})
    e.handle("Hey Aradino, hey Aradino.")       # only the wake word: must not light the Arduino Uno box
    assert e.last_intent == "UNKNOWN" and hw.calls == []
    assert "multimeter" in e.handle("Hey Arduino, where is the multimeter?")


def test_recording_stops_after_speech_then_quiet():
    np = pytest.importorskip("numpy")
    from jarvis.voice import until_quiet
    chunk = lambda level: np.full(2000, level, dtype=np.int16)  # 125 ms at 16 kHz
    talk = [chunk(1000)] * 4 + [chunk(6000)] * 12 + [chunk(1000)] * 40
    assert len(until_quiet(iter(talk))) == (4 + 12 + 7) * 2000   # stops 0.875 s after speech ends
    assert len(until_quiet(iter([chunk(1000)] * 80))) == 32 * 2000  # nobody spoke: give up at 4 s
    assert len(until_quiet(iter([chunk(6000)] * 80))) == 48 * 2000  # never stops talking: 6 s cap


def test_camera_finder_moved_missing_and_fallback(con):
    t = {"where is the multimeter": {"intent": "FIND_TOOL", "item": "multimeter"}}  # home: hook 3, angle 79
    e, hw = make(con, t)
    e.rng = type("First", (), {"choice": staticmethod(lambda lines: lines[0])})()  # first line of each set
    e.finder = lambda name: 80                     # seen on its own hook
    assert "hook 3" in e.handle("Where is the multimeter?") and hw.calls[0] == ("point", 80, 75)
    e.finder = lambda name: 107                    # hung near hook 6 (pan 108) instead
    assert "hook 6" in e.handle("Where is the multimeter?") and hw.calls[-2] == ("point", 107, 75)
    hw.calls.clear()
    e.finder = lambda name: None                   # not on the wall, not on loan
    reply = e.handle("Where is the multimeter?")
    assert "on the wall" in reply and "borrowed" in reply or "signed it out" in reply
    assert hw.calls == []                          # never fire the laser at nothing
    def broken(name): raise OSError("no camera")
    e.finder = broken                              # camera unplugged: fall back to the home hook
    assert "hook 3" in e.handle("Where is the multimeter?")


def test_seed_resyncs_an_existing_database(con):
    con.execute("UPDATE locations SET servo_pan=1 WHERE id='H2'")
    db.seed(con)
    assert db.location(con, "H2")["servo_pan"] == 65 and db.get_item(con, "vernier caliper")["location"] == "H2"
    assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == len(db.SEED_ITEMS)


def test_vision_locate_dot_and_calibration():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from jarvis.vision import find_dot, fit, locate, pan_for
    rng = np.random.default_rng(0)
    wall = rng.integers(90, 110, (480, 640, 3), dtype=np.uint8)
    tool = rng.integers(0, 255, (60, 40, 3), dtype=np.uint8)
    wall[200:260, 300:340] = tool
    x, y, score = locate(wall, tool)
    assert abs(x - 320) <= 2 and abs(y - 230) <= 2 and score > 0.9
    assert locate(rng.integers(90, 110, (480, 640, 3), dtype=np.uint8), tool) is None
    on = wall.copy(); on[100, 500, 2] = 255
    assert find_dot(wall, on) == (500, 100) and find_dot(wall, wall) is None
    cal = fit([(100, 50), (300, 90), (500, 130)])
    assert abs(pan_for(400, cal) - 110) < 0.01
    assert pan_for(10_000, cal) == 130             # clamped to where the dot was seen on the wall
