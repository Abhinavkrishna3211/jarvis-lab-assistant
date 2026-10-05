"""Camera tool finder with our Edge Impulse object-detection model (JARVIS-VISION, FOMO, Linux AARCH64 .eim).

The .eim is a program: started with a socket path, it answers JSON messages on that Unix socket (stdlib only,
no Edge Impulse SDK). Each tool's pixel position becomes a (pan, tilt) aim through a hook calibration: with every
tool on its own hook, the camera's view of the tools is fitted against the hook angles jogged by hand.
The camera is fixed beside the pan-tilt head (not on it), so one calibration holds until either is moved."""
import json
import os
import socket
import subprocess
import tempfile
import time

import numpy as np

LABELS = {"STRIPPER": "wire stripper", "VERNIER": "vernier caliper", "MULTIMETER": "multimeter"}  # model label -> item
MIN_SCORE = 0.5


class Model:
    def __init__(self, path):
        sock = os.path.join(tempfile.mkdtemp(), "eim.sock")
        self.proc = subprocess.Popen([path, sock], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):  # the model takes a moment to open its socket
            if os.path.exists(sock):
                break
            time.sleep(0.1)
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(sock)
        self.id = 0
        p = self._send(hello=1)["model_parameters"]
        self.w, self.h = p["image_input_width"], p["image_input_height"]

    def _send(self, **msg):
        self.id += 1
        self.s.sendall(json.dumps(dict(msg, id=self.id)).encode())
        data = b""
        while not data.endswith(b"\0"):  # each reply ends with a NUL byte
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("vision model exited")
            data += chunk
        r = json.loads(data[:-1])
        if not r.get("success"):
            raise RuntimeError(r.get("error", "vision model failed"))
        return r

    def detect(self, frame):
        """BGR frame -> {item name: (x, y, score)} in frame pixels, the best box per tool."""
        import cv2
        rgb = cv2.resize(frame, (self.w, self.h))[:, :, ::-1].astype(np.int32)  # squash, as in training
        feats = ((rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]).ravel().tolist()
        boxes = self._send(classify=feats)["result"].get("bounding_boxes", [])
        return boxes_to_tools(boxes, frame.shape[1] / self.w, frame.shape[0] / self.h)


def boxes_to_tools(boxes, sx=1.0, sy=1.0):
    out = {}
    for b in boxes:
        name = LABELS.get(b["label"].upper())
        if name and b["value"] >= MIN_SCORE and b["value"] > out.get(name, (0, 0, 0))[2]:
            out[name] = ((b["x"] + b["width"] / 2) * sx, (b["y"] + b["height"] / 2) * sy, b["value"])
    return out


def hook_fit(seen, home):
    """seen: model output with every tool on its own hook; home: {item name: (pan, tilt)} jogged by hand.
    Least-squares map from pixel to both angles, centred on the hooks' mean. Hooks in one column (collinear)
    give no slope across the column, so the fit never guesses beyond what the hooks show."""
    pts = [(seen[n][:2], a) for n, a in home.items() if n in seen]
    if len(pts) < 2:
        raise ValueError(f"saw only {len(pts)} tools on their hooks, need 2 or more")
    px = np.array([p for p, _ in pts], float)
    ang = np.array([a for _, a in pts], float)
    m_px, m_ang = px.mean(0), ang.mean(0)
    g = np.linalg.lstsq(px - m_px, ang - m_ang, rcond=None)[0]  # 2x2: pixel offset -> angle offset
    return {"m_px": m_px.tolist(), "m_ang": m_ang.tolist(), "g": g.tolist(),
            "lo": ang.min(0).tolist(), "hi": ang.max(0).tolist()}


def aim_for(px, cal):
    """Pixel (x, y) -> (pan, tilt), kept inside the box the calibrated hooks span, so a bad detection can
    never swing the laser off the wall or up to head height."""
    a = np.array(cal["m_ang"]) + (np.array(px[:2], float) - cal["m_px"]) @ np.array(cal["g"])
    return tuple(float(v) for v in np.clip(a, cal["lo"], cal["hi"]))


class Finder:
    """engine.finder: name -> (pan, tilt) where the camera sees the tool, or None if it isn't on the wall.
    Raises if there's no camera, model or calibration; the engine then trusts the home hook."""

    def __init__(self, data, grab, model_path):
        self.data, self.grab, self.model_path, self._model = data, grab, model_path, None

    def model(self):
        if self._model is None:
            self._model = Model(self.model_path)
        return self._model

    def __call__(self, name):
        with open(os.path.join(self.data, "vision.json")) as f:
            cal = json.load(f)
        t0 = time.time()
        try:
            seen = self.model().detect(self.grab())
        except Exception:
            self._model = None  # restart the model next time
            raise
        print(f"[vision] {time.time() - t0:.2f}s {seen}")
        m = seen.get(name)
        return None if m is None else aim_for(m, cal)
