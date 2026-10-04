"""Laptop simulator: typed input, simulated hardware, same engine and dashboard as the board.
Run from the repo root:  python python/jarvis/app.py   (or: cd python && python -m jarvis.app)
On the UNO Q, App Lab runs python/main.py instead."""
import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis import db  # noqa: E402
from jarvis.dashboard import make_server  # noqa: E402
from jarvis.engine import Engine  # noqa: E402
from jarvis.hardware import SimHardware  # noqa: E402
from jarvis.llm import HybridLLM, LlamaServerLLM, keyword_parse  # noqa: E402


class KeywordLLM:
    """The rule-based baseline, so the simulator works without a model server."""
    parse = staticmethod(keyword_parse)


def main():
    ap = argparse.ArgumentParser(description="JARVIS simulator (typed input, no hardware)")
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--llm-url", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:8080/v1 "
                                      "(default: keyword baseline, no model)")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    con = db.connect(a.db)
    db.seed(con)
    llm = HybridLLM(LlamaServerLLM(a.llm_url)) if a.llm_url else KeywordLLM()  # same parser as the board
    engine = Engine(con, llm, SimHardware(verbose=True))
    threading.Thread(target=make_server(engine, port=a.port).serve_forever, daemon=True).start()
    print(f"Dashboard on http://127.0.0.1:{a.port}")
    print("JARVIS>", engine.greet())
    while True:
        try:
            text = input("you> ")
        except (EOFError, KeyboardInterrupt):
            break
        print("JARVIS>", engine.handle(text))


if __name__ == "__main__":
    main()
