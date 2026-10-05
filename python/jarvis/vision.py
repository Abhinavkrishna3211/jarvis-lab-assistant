"""Camera tool finder: find a tool on the wall by template matching (no training), then turn its pixel
position into a pan angle using a calibration where the camera watched the laser dot sweep the wall.

One servo, so only one image axis matters (sideways or up/down, chosen at calibration). Templates live in data/tools/<name>.png
(cropped once from a photo of the wall); the calibration in data/vision.json."""
import json
import os

import numpy as np

MIN_SCORE = 0.6                    # TM_CCOEFF_NORMED; below this the tool counts as not on the wall
SCALES = (0.85, 1.0, 1.15)         # small size changes: tool hung slightly nearer or further


def locate(frame, template, min_score=MIN_SCORE):
    """Best match of template in frame -> (centre_x, centre_y, score), or None if it isn't there."""
    import cv2
    img = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tpl0 = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    best = None
    for s in SCALES:
        tpl = cv2.resize(tpl0, None, fx=s, fy=s)
        h, w = tpl.shape
        if h > img.shape[0] or w > img.shape[1]:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED))
        if best is None or score > best[2]:
            best = (x + w / 2, y + h / 2, score)
    return best if best and best[2] >= min_score else None


def find_dot(off, on, min_jump=60):
    """Laser dot = the pixel that got much redder between a laser-off and a laser-on frame -> (x, y) or None."""
    red = on[:, :, 2].astype(np.int16) - off[:, :, 2].astype(np.int16)
    y, x = np.unravel_index(np.argmax(red), red.shape)
    return (int(x), int(y)) if red[y, x] >= min_jump else None


def fit(samples):
    """[(dot_x, pan), ...] from the sweep -> calibration dict. Straight line: fine over a ~90° sweep."""
    xs, pans = zip(*samples)
    a, b = np.polyfit(xs, pans, 1)
    return {"a": float(a), "b": float(b), "pan_min": min(pans), "pan_max": max(pans)}


def pan_for(x, cal):
    """Pixel x -> pan angle, kept inside the range where the dot was actually seen on the wall,
    so a bad match can never swing the laser off the wall."""
    return max(cal["pan_min"], min(cal["pan_max"], cal["a"] * x + cal["b"]))


class Finder:
    """engine.finder: name -> pan angle where the tool is, or None if it isn't on the wall.
    Raises if there's no camera, template or calibration; the engine then trusts the home hook."""

    def __init__(self, data, grab):
        self.data, self.grab = data, grab   # grab() -> one BGR frame

    def __call__(self, name):
        import cv2
        with open(os.path.join(self.data, "vision.json")) as f:
            cal = json.load(f)
        tpl = cv2.imread(os.path.join(self.data, "tools", f"{name}.png"))
        if tpl is None:
            raise FileNotFoundError(f"no template for {name}")
        m = locate(self.grab(), tpl)
        return None if m is None else pan_for(m[cal.get("axis", 0)], cal)  # axis 1: servo moves the dot up/down
