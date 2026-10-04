"""SQLite layer. All stock arithmetic, dates and overdue checks live here, never in the model."""
import sqlite3
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS locations(
  id TEXT PRIMARY KEY, type TEXT CHECK(type IN ('hook','box')),
  servo_pan REAL, servo_tilt REAL, led_index INTEGER);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, aliases TEXT DEFAULT '', uses TEXT DEFAULT '',
  kind TEXT CHECK(kind IN ('tool','component')), location TEXT REFERENCES locations(id),
  qty INTEGER DEFAULT 1, low_stock_at INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS loans(
  id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES items(id), qty INTEGER,
  borrower TEXT, out_date TEXT, due_date TEXT, returned_date TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, time TEXT, transcript TEXT, intent TEXT, result TEXT);
"""

# Placeholder calibration: replace servo angles / LED indexes after calibrating in the real lab.
# Hooks sit in ONE horizontal row at the laser's height, so only the pan servo moves and the tilt
# servo angle is a single fixed value. Calibrate TILT_FIXED and each hook's pan angle on the wall.
TILT_FIXED = 75
SEED_LOCATIONS = [(f"H{i}", "hook", 60 + 8 * i, TILT_FIXED, None) for i in range(1, 9)] + \
                 [(f"B{i}", "box", None, None, i - 1) for i in range(1, 9)]
SEED_ITEMS = [
    # name, aliases, uses, kind, location, qty, low_stock_at
    ("wire stripper", "stripper,wire strippers", "strip insulation from wire", "tool", "H1", 1, 0),
    ("side cutters", "cutters,snips,flush cutters,diagonal cutters",
     "cut zip ties,cut wire,trim component leads,snip", "tool", "H2", 1, 0),
    ("multimeter", "meter,dmm", "measure voltage,check continuity,measure resistance", "tool", "H3", 1, 0),
    ("soldering iron", "iron,solder iron", "solder joints,join wires,desolder", "tool", "H4", 1, 0),
    ("screwdriver set", "screwdriver,screwdrivers", "tighten screws,open cases", "tool", "H5", 1, 0),
    ("tweezers", "tweezer", "pick up small parts,place smd components", "tool", "H6", 1, 0),
    ("hot glue gun", "glue gun", "glue parts,fix things in place", "tool", "H7", 1, 0),
    ("pliers", "needle nose pliers,long nose pliers", "bend wire,hold small parts,grip", "tool", "H8", 1, 0),
    ("ESP32", "esp,esp 32,esp32s,esp thirty two,esp32 board", "", "component", "B1", 10, 3),
    ("Arduino Uno", "uno,arduino uno r3,arduino", "", "component", "B2", 6, 2),
    ("Raspberry Pi Pico", "pico,rp2040,pi pico", "", "component", "B3", 5, 2),
    ("DHT22 sensor", "dht22,dht,temperature sensor,humidity sensor", "", "component", "B4", 8, 2),
    ("ultrasonic sensor", "hc-sr04,distance sensor,sonar", "", "component", "B5", 7, 2),
    ("SG90 servo", "servo,servos,sg90", "", "component", "B6", 12, 3),
    ("OLED display", "oled,ssd1306,display", "", "component", "B7", 6, 2),
    ("jumper wires", "jumpers,jumper wire,wires", "", "component", "B8", 100, 20),
]


def connect(path=":memory:"):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def seed(con):
    if con.execute("SELECT COUNT(*) FROM items").fetchone()[0]:
        return
    con.executemany("INSERT INTO locations VALUES(?,?,?,?,?)", SEED_LOCATIONS)
    con.executemany(
        "INSERT INTO items(name,aliases,uses,kind,location,qty,low_stock_at) VALUES(?,?,?,?,?,?,?)",
        SEED_ITEMS)
    con.commit()


def all_items(con):
    return [dict(r) for r in con.execute("SELECT * FROM items")]


def get_item(con, name):
    r = con.execute("SELECT * FROM items WHERE lower(name)=lower(?)", (name,)).fetchone()
    return dict(r) if r else None


def location(con, loc_id):
    r = con.execute("SELECT * FROM locations WHERE id=?", (loc_id,)).fetchone()
    return dict(r) if r else None


def on_loan(con, item_id):
    """Total quantity currently out for an item."""
    return con.execute(
        "SELECT COALESCE(SUM(qty),0) FROM loans WHERE item_id=? AND returned_date IS NULL",
        (item_id,)).fetchone()[0]


def available(con, item):
    """Stock on the shelf = qty owned minus open loans."""
    return item["qty"] - on_loan(con, item["id"])


def open_loans(con, item_id=None, borrower=None):
    q = ("SELECT l.*, i.name AS item FROM loans l JOIN items i ON i.id=l.item_id "
         "WHERE l.returned_date IS NULL")
    args = []
    if item_id is not None:
        q += " AND l.item_id=?"; args.append(item_id)
    if borrower:
        q += " AND lower(l.borrower)=lower(?)"; args.append(borrower)
    return [dict(r) for r in con.execute(q + " ORDER BY l.out_date", args)]


def overdue(con, today=None):
    today = (today or date.today()).isoformat()
    return [l for l in open_loans(con) if l["due_date"] < today]


def lend(con, item, qty, borrower, due, today=None):
    if qty < 1 or qty > available(con, item):
        raise ValueError("insufficient stock")
    con.execute("INSERT INTO loans(item_id,qty,borrower,out_date,due_date) VALUES(?,?,?,?,?)",
                (item["id"], qty, borrower, (today or date.today()).isoformat(), due))
    con.commit()


def give_back(con, item, borrower, qty=None, today=None):
    """Close the oldest open loan(s) for this borrower and item. Returns qty returned."""
    loans = open_loans(con, item["id"], borrower)
    if not loans:
        return 0
    returned = 0
    want = qty if qty else sum(l["qty"] for l in loans)
    for l in loans:
        if returned >= want:
            break
        con.execute("UPDATE loans SET returned_date=? WHERE id=?",
                    ((today or date.today()).isoformat(), l["id"]))
        returned += l["qty"]
    con.commit()
    return returned


def log_event(con, transcript, intent, result, now):
    con.execute("INSERT INTO events(time,transcript,intent,result) VALUES(?,?,?,?)",
                (now, transcript, intent, result))
    con.commit()
