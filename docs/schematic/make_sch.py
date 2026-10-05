"""Generates docs/schematic/jarvis.kicad_sch from KiCad 10's stock symbol libraries.

    python docs/schematic/make_sch.py docs/schematic/jarvis.kicad_sch
"""
import re
import sys
import uuid

LIB = "C:/Program Files/KiCad/10.0/share/kicad/symbols/"
OUT = sys.argv[1]
U = lambda: str(uuid.uuid4())
ROOT = U()
INK = "(color 0 0 0 1)"
FRAME = "(color 132 132 132 1)"


# ------------------------------------------------------------------ library access
def sexpr_end(s, i):
    d = 0
    for j in range(i, len(s)):
        d += (s[j] == "(") - (s[j] == ")")
        if d == 0:
            return j + 1


def children(block):
    out, i = [], block.index("(", block.index("(") + 1)
    while i < len(block) - 1:
        if block[i] == "(":
            j = sexpr_end(block, i)
            out.append(block[i:j])
            i = j
        else:
            i += 1
    return out


_src = {}


def lib_symbol(f, name):
    """The symbol block, with 'extends' flattened into a standalone symbol."""
    s = _src.setdefault(f, open(LIB + f, encoding="utf-8").read())
    i = s.index(f'\t(symbol "{name}"\n') + 1
    b = s[i:sexpr_end(s, i)]
    m = re.search(r'\(extends "([^"]+)"\)', b)
    if not m:
        return b
    props = [c for c in children(b) if c.startswith("(property")]
    body = [c.replace(f'(symbol "{m[1]}_', f'(symbol "{name}_') for c in children(lib_symbol(f, m[1]))
            if not c.startswith("(property")]
    return f'(symbol "{name}"\n' + "\n".join(props + body) + ")"


PIN = re.compile(r'\(pin \w+ \w+\s+\(at ([-\d.]+) ([-\d.]+) \d+\).*?\(name "([^"]*)".*?\(number "([^"]*)"', re.S)
libsyms, PINS = [], {}


def use(lib_id, f):
    nm = lib_id.split(":")[1]
    b = lib_symbol(f, nm)
    libsyms.append(b.replace(f'(symbol "{nm}"', f'(symbol "{lib_id}"', 1))
    for sub in re.finditer(r'\(symbol "[^"]+_(\d+)_\d+"', b):
        part = b[sub.start():sexpr_end(b, sub.start())]
        for m in PIN.finditer(part):
            p = PINS.setdefault((lib_id, int(sub[1])), {})
            p[m[4]] = (float(m[1]), float(m[2]))
            p.setdefault(m[3], (float(m[1]), float(m[2])))


for lib_id, f in (("Device:R", "Device.kicad_sym"), ("Device:C", "Device.kicad_sym"),
                  ("Device:C_Polarized", "Device.kicad_sym"), ("Device:D_Laser_1C2A", "Device.kicad_sym"),
                  ("Transistor_FET:IRLZ44N", "Transistor_FET.kicad_sym"),
                  ("MCU_Module:Arduino_UNO_R3", "MCU_Module.kicad_sym"), ("Motor:Motor_Servo", "Motor.kicad_sym"),
                  ("LED:WS2812B", "LED.kicad_sym"), ("74xx:74AHCT125", "74xx.kicad_sym"),
                  ("Connector_Generic:Conn_01x02", "Connector_Generic.kicad_sym"),
                  ("power:+5V", "power.kicad_sym"), ("power:GND", "power.kicad_sym"),
                  ("power:PWR_FLAG", "power.kicad_sym")):
    use(lib_id, f)

# ------------------------------------------------------------------ drawing helpers
items = []


def r2(v):
    return round(v, 2)


def place(lib_id, ref, value, x, y, rot=0, mirror=False, unit=1, ref_at=None, val_at=None, just="left", fa=0):
    """Places a symbol; returns {pin number or name: (x, y)} in sheet coordinates."""
    pos = {}
    for u in (0, unit):
        for k, (px, py) in PINS.get((lib_id, u), {}).items():
            sx, sy = (-px if mirror else px), -py
            for _ in range(rot // 90):  # counter-clockwise on screen
                sx, sy = sy, -sx
            pos[k] = (r2(x + sx), r2(y + sy))
    ref_at = ref_at or (x + 2.54, y - 1.27)
    val_at = val_at or (x + 2.54, y + 1.27)
    j = "" if just == "center" else f"(justify {just})"
    m = "(mirror y) " if mirror else ""
    items.append(f'''(symbol (lib_id "{lib_id}") (at {x} {y} {rot}) {m}(unit {unit}) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no) (uuid "{U()}")
  (property "Reference" "{ref}" (at {r2(ref_at[0])} {r2(ref_at[1])} {fa}) (effects (font (size 1.27 1.27)) {j}))
  (property "Value" "{value}" (at {r2(val_at[0])} {r2(val_at[1])} {fa}) (effects (font (size 1.27 1.27)) {j}))
  (property "Footprint" "" (at {x} {y} 0) (hide yes) (effects (font (size 1.27 1.27))))
  (property "Datasheet" "" (at {x} {y} 0) (hide yes) (effects (font (size 1.27 1.27))))
  (instances (project "jarvis" (path "/{ROOT}" (reference "{ref}") (unit {unit})))))''')
    return pos


_pwr = [0]


def pwr(name, p, rot=0):
    """+5V / PWR_FLAG point up and GND points down at rot 0; rot 90 turns +5V to point left."""
    _pwr[0] += 1
    ref = f"#FLG{_pwr[0]:02d}" if name == "PWR_FLAG" else f"#PWR{_pwr[0]:02d}"
    if rot == 90:
        at, j = (p[0] - 3.81, p[1]), "(justify left)"  # rot 90 flips justify
    else:
        at, j = (p[0], p[1] + (3.81 if name == "GND" else -3.81)), ""
    items.append(f'''(symbol (lib_id "power:{name}") (at {p[0]} {p[1]} {rot}) (unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no) (uuid "{U()}")
  (property "Reference" "{ref}" (at {p[0]} {p[1]} 0) (hide yes) (effects (font (size 1.27 1.27))))
  (property "Value" "{name}" (at {r2(at[0])} {r2(at[1])} {rot}) (effects (font (size 1.27 1.27)) {j}))
  (property "Footprint" "" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
  (property "Datasheet" "" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
  (instances (project "jarvis" (path "/{ROOT}" (reference "{ref}") (unit 1)))))''')


def wire(*pts):
    """Wire through the points; a diagonal step becomes horizontal-then-vertical."""
    for a, b in zip(pts, pts[1:]):
        if a[0] != b[0] and a[1] != b[1]:
            c = (b[0], a[1])
            items.append(f'(wire (pts (xy {a[0]} {a[1]}) (xy {c[0]} {c[1]})) (stroke (width 0) (type default)) (uuid "{U()}"))')
            a = c
        items.append(f'(wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]})) (stroke (width 0) (type default)) (uuid "{U()}"))')


def dot(p):
    items.append(f'(junction (at {p[0]} {p[1]}) (diameter 0) (color 0 0 0 0) (uuid "{U()}"))')


def nc(p):
    items.append(f'(no_connect (at {p[0]} {p[1]}) (uuid "{U()}"))')


def glabel(name, p, shape, left=False):
    """Global label whose connection point is p; the flag extends right, or left with left=True."""
    rot, j = (180, "right") if left else (0, "left")
    items.append(f'(global_label "{name}" (shape {shape}) (at {p[0]} {p[1]} {rot}) (fields_autoplaced yes) '
                 f'(effects (font (size 1.27 1.27)) (justify {j})) (uuid "{U()}"))')


def text(s, x, y, size=1.27, bold=False, just="left"):
    b = " (bold yes)" if bold else ""
    j = "" if just == "center" else f" (justify {just} bottom)"
    items.append(f'(text "{s}" (exclude_from_sim no) (at {x} {y} 0) (effects (font (size {size} {size}){b} {INK}){j}) (uuid "{U()}"))')


def line(*pts, dash=False):
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    t = "dash" if dash else "solid"
    items.append(f'(polyline (pts {xy}) (stroke (width 0.2) (type {t}) {INK}) (uuid "{U()}"))')


def rect(x1, y1, x2, y2, dash=False, width=0.2, color=INK):
    t = "dash" if dash else "solid"
    items.append(f'(rectangle (start {x1} {y1}) (end {x2} {y2}) (stroke (width {width}) (type {t}) {color}) (fill (type none)) (uuid "{U()}"))')


def block(title, x1, y1, x2, y2):
    """Thin dashed frame around one functional block, title top-left."""
    rect(x1, y1, x2, y2, dash=True, width=0.15, color=FRAME)
    text(title, x1 + 2.54, y1 + 5.08, 1.778, bold=True)


def box(label, x1, y1, x2, y2, dash=False):
    """Off-the-shelf module in the system diagram."""
    rect(x1, y1, x2, y2, dash=dash)
    for i, s in enumerate(label.split("|")):
        text(s, r2((x1 + x2) / 2), r2((y1 + y2) / 2 + (i - (label.count("|")) / 2) * 2.54 + 0.6), just="center")


def cap(lib_id, ref, value, x, y):
    C = place(lib_id, ref, value, x, y)
    pwr("+5V", C["1"])
    pwr("GND", C["2"])


# ------------------------------------------------------------------ POWER INPUT
block("POWER INPUT  5 V / 4 A", 20.32, 40.64, 109.22, 132.08)
J1 = place("Connector_Generic:Conn_01x02", "J1", "5V 4A DC IN", 38.1, 76.2, mirror=True,
           ref_at=(35.56, 76.2), val_at=(35.56, 78.74))  # mirror flips justify: reads right-aligned
p1, p2 = J1["1"], J1["2"]
wire(p1, (55.88, p1[1]), (64.77, p1[1]), (71.12, p1[1]), (71.12, 80.01))
pwr("PWR_FLAG", (55.88, p1[1])); dot((55.88, p1[1]))
pwr("+5V", (64.77, p1[1])); dot((64.77, p1[1]))
C1 = place("Device:C_Polarized", "C1", "1000uF 10V", 71.12, 83.82)
pwr("GND", C1["2"])
cap("Device:C", "C2", "100nF", 88.9, 83.82)
wire(p2, (45.72, p2[1]), (45.72, 91.44), (50.8, 91.44))
pwr("GND", (45.72, 93.98)); wire((45.72, 91.44), (45.72, 93.98)); dot((45.72, 91.44))
pwr("PWR_FLAG", (50.8, 91.44))

# ------------------------------------------------------------------ MCU
block("MCU  Arduino UNO Q (UNO R3 header layout)", 114.3, 40.64, 209.55, 132.08)
ax, ay = 162.56, 88.9
A1 = place("MCU_Module:Arduino_UNO_R3", "A1", "Arduino UNO Q", ax, ay, mirror=True,
           ref_at=(ax - 15.24, 57.15), val_at=(ax - 15.24, 59.69))
for pin, net in (("20", "SERVO_PAN"), ("21", "SERVO_TILT"), ("22", "LASER_EN"), ("23", "NEO_STRIP"), ("24", "NEO_RING")):
    end = (r2(A1[pin][0] + 7.62), A1[pin][1])
    wire(A1[pin], end)
    glabel(net, end, "output")
for pin in ("2", "3", "4", "5", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19",
            "25", "26", "27", "28", "30", "31", "32"):
    nc(A1[pin])
g = sorted([A1["6"], A1["7"], A1["29"]])
wire(*g)
mid = g[1]
wire(mid, (mid[0], r2(mid[1] + 2.54))); dot(mid)
pwr("GND", (mid[0], r2(mid[1] + 2.54)))
text("USB-C: power + data from the hub (see SYSTEM)", 119.38, 127.0)

# ------------------------------------------------------------------ LASER DRIVER
block("LASER DRIVER  low-side switch", 214.63, 40.64, 302.26, 132.08)
Q1 = place("Transistor_FET:IRLZ44N", "Q1", "IRLZ44N", 271.78, 101.6,
           ref_at=(276.86, 100.33), val_at=(276.86, 102.87))
qd, qs, qg = Q1["D"], Q1["S"], Q1["G"]
LD1 = place("Device:D_Laser_1C2A", "LD1", "Laser module", qd[0], 83.82, rot=90,
            ref_at=(qd[0] + 5.08, 82.55), val_at=(qd[0] + 5.08, 85.09), fa=90, just="right")  # rot 90 flips justify
R1 = place("Device:R", "R1", "150R 0.25W", qd[0], 68.58)
pwr("+5V", R1["1"])
wire(R1["2"], LD1["A"])
wire(LD1["K"], qd)
pwr("GND", qs)
R2 = place("Device:R", "R2", "270R", 251.46, qg[1], rot=90,
           ref_at=(251.46, qg[1] - 2.54), val_at=(251.46, qg[1] + 2.54), just="center")
r2l, r2r = sorted([R2["1"], R2["2"]])
node = (259.08, qg[1])
wire(r2r, node, qg); dot(node)
R3 = place("Device:R", "R3", "10k", 259.08, qg[1] + 7.62)
wire(node, R3["1"])
pwr("GND", R3["2"])
wire(r2l, (238.76, qg[1]))
glabel("LASER_EN", (238.76, qg[1]), "input", left=True)

# ------------------------------------------------------------------ SYSTEM
block("SYSTEM  USB and audio", 307.34, 40.64, 405.13, 132.08)
box("USB-C PD charger|45 W or more", 317.5, 55.88, 355.6, 66.04)
box("Powered USB-C hub|PD pass-through", 317.5, 78.74, 355.6, 88.9)
box("Arduino UNO Q|USB-C port", 317.5, 101.6, 355.6, 111.76)
box("USB camera|with built-in mic", 365.76, 78.74, 400.05, 88.9)
box("Bluetooth speaker", 365.76, 101.6, 400.05, 111.76, dash=True)
line((336.55, 66.04), (336.55, 78.74)); text("USB-C PD", 338.33, 73.66)
line((336.55, 88.9), (336.55, 101.6)); text("USB-C power + data", 338.33, 96.52)
line((355.6, 83.82), (365.76, 83.82)); text("USB 2.0", 356.87, 82.55)
line((355.6, 106.68), (365.76, 106.68), dash=True); text("BT", 358.14, 105.41)
text("Camera: tool finder video, wake word and speech audio", 312.42, 120.65)
text("Speaker: Bluetooth, no wiring", 312.42, 124.46)

# ------------------------------------------------------------------ SERVOS
LOW = len(items)  # lower row drawn on the old grid, lifted below
block("SERVOS  pan D5, tilt D6", 20.32, 147.32, 109.22, 252.73)
for i, (ref, val, net) in enumerate((("M1", "SG90 pan", "SERVO_PAN"), ("M2", "SG90 tilt", "SERVO_TILT"))):
    y = 177.8 + i * 33.02
    M = place("Motor:Motor_Servo", ref, val, 71.12, y, ref_at=(80.01, y - 2.54), val_at=(80.01, y))
    wire(M["PWM"], (48.26, M["PWM"][1]))
    glabel(net, (48.26, M["PWM"][1]), "input", left=True)
    pwr("+5V", M["+"], rot=90)
    corner = (r2(M["-"][0] - 2.54), M["-"][1])
    wire(M["-"], corner, (corner[0], r2(corner[1] + 5.08)))
    pwr("GND", (corner[0], r2(corner[1] + 5.08)))
C3 = place("Device:C_Polarized", "C3", "1000uF 10V", 93.98, 185.42)
pwr("+5V", C3["1"]); pwr("GND", C3["2"])
cap("Device:C", "C4", "100nF", 93.98, 215.9)

# ------------------------------------------------------------------ NEOPIXELS
block("NEOPIXELS  3.3 V to 5 V level shift", 114.3, 147.32, 259.08, 252.73)
for k, (unit, net, led, val, y) in enumerate(((1, "NEO_STRIP", "D1", "WS2812B strip, 8 LEDs", 172.72),
                                              (2, "NEO_RING", "D2", "WS2812B ring, 16 LEDs", 205.74))):
    G = place("74xx:74AHCT125", "U1", "74AHCT125", 157.48, y, unit=unit,
              ref_at=(157.48, y - 8.89), val_at=(157.48, y - 6.35), just="center")
    wire(G["2" if unit == 1 else "5"], (139.7, y))
    glabel(net, (139.7, y), "input", left=True)
    pwr("GND", G["1" if unit == 1 else "4"])
    R = place("Device:R", f"R{4 + k}", "330R", 175.26, y, rot=90,
              ref_at=(175.26, y - 2.54), val_at=(175.26, y + 2.54), just="center")
    rl, rr = sorted([R["1"], R["2"]])
    wire(G["3" if unit == 1 else "6"], rl)
    D = place("LED:WS2812B", led, val, 200.66, y, ref_at=(207.01, y - 6.35), val_at=(207.01, y - 3.81))
    wire(rr, D["DIN"])
    pwr("+5V", D["VDD"]); pwr("GND", D["VSS"])
    nc(D["DOUT"])
    text("DOUT chains to the next LED", 207.01, y + 5.08)
C5 = place("Device:C_Polarized", "C5", "1000uF 10V", 243.84, 172.72)
pwr("+5V", C5["1"]); pwr("GND", C5["2"])
P = place("74xx:74AHCT125", "U1", "74AHCT125", 129.54, 233.68, unit=5,
          ref_at=(134.62, 232.41), val_at=(134.62, 234.95))
pwr("+5V", P["14"]); pwr("GND", P["7"])
cap("Device:C", "C6", "100nF", 152.4, 233.68)
for unit, x in ((3, 185.42), (4, 223.52)):
    G = place("74xx:74AHCT125", "U1", "74AHCT125", x, 228.6, unit=unit,
              ref_at=(x, 219.71), val_at=(x, 222.25), just="center")
    a = G["9" if unit == 3 else "12"]
    wire(a, (r2(a[0] - 2.54), a[1]), (r2(a[0] - 2.54), r2(a[1] + 5.08)))
    pwr("GND", (r2(a[0] - 2.54), r2(a[1] + 5.08)))
    pwr("GND", G["10" if unit == 3 else "13"])
    nc(G["8" if unit == 3 else "11"])

# ------------------------------------------------------------------ NOTES
NOTES = [
    "NOTES",
    "1. Pin map (matches sketch/sketch.ino): D5 SERVO_PAN (TIM1), D6 SERVO_TILT (TIM3), D7 LASER_EN (PB2,",
    "    TIM8, plain GPIO), D8 NEO_STRIP, D9 NEO_RING. MCU GPIO is 3.3 V, 5 V tolerant except A0/A1.",
    "2. R1 = (5.0 V - 2.2 V) / 20 mA = 140R, use 150R: about 19 mA, 0.05 W. If the module keeps its own",
    "    resistor the current is lower; measure before fitting.",
    "3. R2: gate charge peak 3.3 V / 270R = 12 mA. R3 holds Q1 off during boot and reset.",
    "4. LD1 is a salvaged low-power keychain laser module, output power unmeasured. Firmware switches",
    "    it off after 10 s (sketch.ino and hardware.py). Never aim at people or at head height.",
    "5. U1 (74AHCT125, VIH 2.0 V) lifts 3.3 V data to 5 V; WS2812B needs VIH 0.7 x VDD = 3.5 V.",
    "    Unused gates 3 and 4: inputs and OE to GND, outputs open. R4, R5 at the first LED.",
    "6. Servos (about 0.7 A stall each) and LEDs run from J1, never from the UNO Q 5 V pin.",
    "    J1 GND, UNO Q GND, Q1 source, servo and LED grounds are common.",
    "7. Load budget: servos 1.4 A + LEDs 24 x 60 mA = 1.44 A + laser 0.02 A = 2.9 A worst case.",
    "8. All resistors 0.25 W 5 %. Electrolytics 10 V or more.",
]
rect(264.16, 147.32, 405.13, 252.73, width=0.15, color=FRAME)
for i, s in enumerate(NOTES):
    text(s, 266.7, 153.67 + i * 3.81 + (1.27 if i else 0), 1.778 if i == 0 else 1.27, bold=(i == 0))

# ------------------------------------------------------------------ file
items[:] = [re.sub(r"\((at|xy|start|end) ([-\d.]+) ([-\d.]+)", lambda m, d=(25.4 if k >= LOW else 15.24): f"({m[1]} {m[2]} {r2(float(m[3]) - d)}", it)
            for k, it in enumerate(items)]
sch = f'''(kicad_sch (version 20250114) (generator "eeschema") (generator_version "10.0")
  (uuid "{ROOT}")
  (paper "A3")
  (title_block (title "JARVIS Lab Assistant - Main Wiring")
    (date "2026-10-05") (rev "B") (company "Designed by Abhinav Krishna")
    (comment 1 "Arduino UNO Q: servos, laser driver, NeoPixels, USB camera")
    (comment 2 "Pin map matches sketch/sketch.ino"))
  (lib_symbols
{chr(10).join(libsyms)}
  )
{chr(10).join(items)}
  (sheet_instances (path "/" (page "1")))
)
'''
open(OUT, "w", encoding="utf-8").write(sch)
print("ok", len(items), "items")
