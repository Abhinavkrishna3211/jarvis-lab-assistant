"""Request pipeline: transcript -> candidates -> LLM JSON -> validation -> action -> spoken reply.
Loans and returns always need a spoken yes (or a tap) before anything is written."""
import re
import threading
from datetime import date, datetime

from . import db, dialogue
from .dates import speakable
from .matcher import candidates
from .validate import Invalid, validate

YES = re.compile(r"^\s*(yes|yeah|yep|confirm|confirmed|go ahead|do it|log it|please do|affirmative)\b", re.I)
# Whisper often keeps the wake word ("Hey Aradino, where is..."), and "arduino" then matches the Arduino Uno.
WAKE = re.compile(r"^(\W*(hey|hi|hay|okay|ok)\W+(jarvis|ar\w*d\w*no)\b)+\W*", re.I)
NO = re.compile(r"^\s*(no|nope|cancel|stop|never ?mind|negative|don't)\b", re.I)
# Small talk, answered in code before any parsing. Only short phrases (<= 6 words), so
# "thanks, where's the multimeter" still goes to the parser. BYE before THANKS: "no thanks" ends.
CHAT = [(re.compile(r"^\s*(no|nope|nothing|that's all|that is all|i'm good|i am good|all good|bye|goodbye)\b", re.I),
         "BYE", "goodbye"),
        (re.compile(r"^\W*(thank you|thanks|cheers)( (so much|very much|jarvis|sir))?\W*$", re.I), "THANKS", "thanks"),
        (re.compile(r"\b(who are you|what are you|your name)\b", re.I), "CHAT", "whoami"),
        (re.compile(r"\bhow are you\b", re.I), "CHAT", "how"),
        (re.compile(r"^\W*((which|what) tool (should|do|can|shall) i use|i (need|want) (a|some) tool"
                    r"|i have (a|this) (need|job|task))\W*$", re.I), "CHAT", "ask_task"),
        (re.compile(r"^\s*(what can you do|help)\W*$", re.I), "CHAT", "help")]


HOOK_TOL = 4  # degrees: a tool seen within this of its hook's pan angle is on its hook


class Engine:
    def __init__(self, con, llm, hw, today=None, rng=None, coordinator="sir", finder=None):
        self.con, self.llm, self.hw = con, llm, hw
        self.finder = finder  # vision.Finder: where the camera sees a tool (None = trust the home hook)
        self._today, self.coordinator = today, coordinator
        self.pending = None
        self.last_intent = None  # main.py ends the conversation on THANKS / BYE
        self.asking_task = False  # asked "what's the job?": the next answer is a task, not a new request
        self.lock = threading.Lock()  # voice loop and dashboard both call in
        import random
        self.rng = rng or random.Random()

    def today(self):
        return self._today or date.today()

    def _say(self, key, **kw):
        return dialogue.say(key, self.rng, **kw)

    # ------------------------------------------------------------ public
    def greet(self, hour=None):
        """Spoken right after the wake word."""
        h = datetime.now().hour if hour is None else hour
        part = "morning" if 4 <= h < 12 else "afternoon" if h < 17 else "evening"
        return self._say("wake", part=part, name=self.coordinator)

    def handle(self, transcript):
        """Returns the reply text. Hardware side effects go through self.hw."""
        with self.lock:
            return self._handle(transcript)

    def _handle(self, transcript):
        transcript = WAKE.sub("", transcript).strip()
        if self.pending:
            self.last_intent = "CONFIRM"
            return self._confirm(transcript)
        if self.asking_task:
            self.asking_task = False
            transcript = "I need a tool to " + transcript  # "measure the diameter" -> tool for that task
        intent, reply = "UNKNOWN", None
        for rx, chat_intent, key in CHAT:
            if len(transcript.split()) <= 6 and rx.search(transcript):
                intent, reply = chat_intent, self._say(key)
                self.asking_task = key == "ask_task"
                break
        else:
            intent, reply = self._parse_and_act(transcript)
        self.last_intent = intent
        db.log_event(self.con, transcript, intent, reply, datetime.now().isoformat(timespec="seconds"))
        return reply

    def _parse_and_act(self, transcript):
        intent, reply = "UNKNOWN", None
        try:
            action = self.llm.parse(transcript, candidates(transcript, db.all_items(self.con)))
            clean = validate(action, self.con, self.today())
            intent = clean["intent"]
            reply = self._dispatch(clean)
        except Invalid as e:
            if "inventory" in str(e):
                reply = self._say("not_stocked")
            elif "stock" in str(e):
                reply = self._say("short_stock", item=e.item_name, have=e.have)
            else:
                reply = self._say("unclear")
        except Exception:  # model server down, bad JSON, bridge error: never crash the lab
            reply = self._say("error")
            self.hw.ring_state("error")
        return intent, reply

    # ------------------------------------------------------------ dispatch
    def _dispatch(self, a):
        return getattr(self, "_" + a["intent"].lower())(a)

    def _mark(self, item):
        """Light the box, or aim the laser at the tool. Returns the location to name in the reply
        (the hook nearest to where the camera saw it), or None if the camera can't see it on the wall."""
        loc = db.location(self.con, item["location"])
        if loc["type"] != "hook":
            self.hw.box_led(loc["led_index"], "white")
            return loc
        pan = loc["servo_pan"]
        if self.finder:
            try:
                pan = self.finder(item["name"])
            except Exception as e:  # no camera, template or calibration yet: trust the home hook
                print("[vision]", e)
            if pan is None:
                return None
        self.hw.point(pan, loc["servo_tilt"])
        self.hw.laser(True, 10)
        if abs(pan - loc["servo_pan"]) <= HOOK_TOL:
            return loc
        hooks = self.con.execute("SELECT * FROM locations WHERE type='hook'").fetchall()
        return dict(min(hooks, key=lambda h: abs(h["servo_pan"] - pan)), moved=True)

    def _position(self, loc):
        return f"hook {loc['id'][1:]}" if loc["type"] == "hook" else f"box {loc['id'][1:]}"

    def _find_tool(self, a):
        item = a["item"]
        loans = db.open_loans(self.con, item["id"])
        if loans and db.available(self.con, item) <= 0:
            l = loans[0]
            return self._say("tool_loan", tool=item["name"], borrower=l["borrower"],
                             date=speakable(l["out_date"]), due=speakable(l["due_date"]))
        loc = self._mark(item)
        if loc is None:
            return self._say("tool_missing", tool=item["name"])
        key = "tool_moved" if loc.get("moved") else "tool_found"
        return self._say(key, tool=item["name"], position=self._position(loc))

    def _tool_for_task(self, a):
        item = a["item"]
        if item["kind"] != "tool":
            raise Invalid("item not a tool")
        loc = self._mark(item)
        if loc is None:
            return self._say("tool_missing", tool=item["name"])
        return self._say("tool_task", tool=item["name"], position=self._position(loc))

    def _find_component(self, a):
        item = a["item"]
        left = db.available(self.con, item)
        if left <= 0:
            return self._say("out_stock", item=item["name"])
        loc = self._mark(item)
        key = "low_stock" if left <= item["low_stock_at"] else "comp_found"
        return self._say(key, item=item["name"], qty=left, box=loc["id"][1:])

    _stock = _find_component

    def _lend(self, a):
        self.pending = a
        return self._say("lend_confirm", qty=a["qty"], item=a["item"]["name"],
                         borrower=a["borrower"], due=speakable(a["due"]))

    def _return(self, a):
        open_ = db.open_loans(self.con, a["item"]["id"], a["borrower"])
        if not open_:
            return self._say("no_loan", item=a["item"]["name"], borrower=a["borrower"])
        self.pending = a
        return self._say("return_confirm", qty=a["qty"], item=a["item"]["name"], borrower=a["borrower"])

    def _overdue(self, a):
        late = db.overdue(self.con, self.today())
        if not late:
            return self._say("no_overdue")
        o = late[0]
        names = ", ".join(f"{l['item']} ({l['borrower']})" for l in late[:3])
        if len(late) == 1:
            return self._say("overdue", n=1, item=o["item"], borrower=o["borrower"],
                             date=speakable(o["out_date"]), list=names)
        return f"{len(late)} items are overdue: {names}."

    def _who_has(self, a):
        loans = db.open_loans(self.con, a["item"]["id"])
        if not loans:
            return self._say("nobody", item=a["item"]["name"])
        l = loans[0]
        return self._say("who_has", borrower=l["borrower"], item=a["item"]["name"],
                         date=speakable(l["out_date"]), due=speakable(l["due_date"]))

    # ------------------------------------------------------------ confirmation
    def confirm(self, yes=True):
        """Also called by the dashboard's tap-to-confirm buttons."""
        with self.lock:
            return self._confirm("yes" if yes else "no") if self.pending else ""

    def _confirm(self, transcript):
        a = self.pending
        if YES.match(transcript):
            self.pending = None
            item = a["item"]
            if a["intent"] == "LEND":
                try:
                    db.lend(self.con, item, a["qty"], a["borrower"], a["due"], self.today())
                except ValueError:
                    return self._say("out_stock", item=item["name"])
                return self._say("lend_saved", qty=a["qty"], item=item["name"], borrower=a["borrower"])
            got = db.give_back(self.con, item, a["borrower"], a["qty"], self.today())
            fresh = db.get_item(self.con, item["name"])
            return self._say("return_saved", qty=got, item=item["name"], borrower=a["borrower"],
                             total=db.available(self.con, fresh))
        if NO.match(transcript):
            self.pending = None
            return self._say("cancelled")
        return "Shall I log it? Yes or no, please."
