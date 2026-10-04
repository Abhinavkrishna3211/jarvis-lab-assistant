"""Score intent/item/qty/borrower accuracy on 60 commands: keyword baseline, and optionally Gemma and the hybrid.
Usage: python eval/run_eval.py [--gemma http://llamacpp-models-runner:9999/v1] [--json out.json]
A command counts as correct only if intent, item, qty (LEND) and borrower (LEND/RETURN) all match
AFTER validation, i.e. exactly what the system would have acted on."""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from jarvis import db  # noqa: E402
from jarvis.llm import HybridLLM, LlamaServerLLM, keyword_parse  # noqa: E402
from jarvis.matcher import candidates  # noqa: E402
from jarvis.validate import Invalid, validate  # noqa: E402

TODAY = date(2026, 10, 4)


def judge(parse, con, items, row):
    text, intent, item, qty, borrower = row
    t0 = time.time()
    try:
        got = validate(parse(text, items), con, TODAY)
    except Invalid:
        got = {"intent": "UNKNOWN"}
    except Exception as e:
        got = {"intent": "ERROR", "error": repr(e)}
    dt = time.time() - t0
    ok = got["intent"] == intent
    if ok and item:
        ok = got.get("item", {}).get("name") == item
    if ok and intent == "LEND":
        ok = got.get("qty") == qty and got.get("borrower") == borrower
    if ok and intent == "RETURN":
        ok = got.get("borrower") == borrower
    return ok, dt, got


def run(name, parse, con, items, rows):
    res = [judge(parse, con, items, r) for r in rows]
    by = {}
    for r, (ok, _, _) in zip(rows, res):
        by.setdefault(r[1], []).append(ok)
    times = sorted(d for _, d, _ in res)
    errors = sum(g["intent"] == "ERROR" for _, _, g in res)
    print(f"\n{name}: {sum(o for o, _, _ in res)}/{len(res)} correct, {errors} errors, "
          f"mean {sum(times)/len(times):.2f}s, median {times[len(times)//2]:.2f}s, max {times[-1]:.2f}s")
    for k, v in sorted(by.items()):
        print(f"  {k:15s} {sum(v)}/{len(v)}")
    return {"correct": sum(o for o, _, _ in res), "total": len(res), "errors": errors,
            "mean_s": sum(times) / len(times), "median_s": times[len(times) // 2], "max_s": times[-1],
            "by_intent": {k: [sum(v), len(v)] for k, v in by.items()},
            "rows": [{"text": r[0], "expected": r[1:], "ok": ok, "seconds": round(d, 3),
                      "got": {k: (v["name"] if isinstance(v, dict) else v) for k, v in g.items()}}
                     for r, (ok, d, g) in zip(rows, res)]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemma")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = json.loads((Path(__file__).parent / "commands.json").read_text())
    con = db.connect(); db.seed(con)
    items = db.all_items(con)
    out = {"keyword": run("keyword baseline", lambda t, i: keyword_parse(t, i), con, items, rows)}
    if a.gemma:
        llm = LlamaServerLLM(a.gemma)
        out["gemma"] = run("Gemma 3 1B + validation", lambda t, i: llm.parse(t, candidates(t, i)), con, items, rows)
        calls = []
        hybrid = HybridLLM(llm, on_slow=lambda: calls.append(1))
        out["hybrid"] = run("Hybrid: keyword rules, Gemma if they give up", lambda t, i: hybrid.parse(t, candidates(t, i)),
                            con, items, rows)
        out["hybrid"]["gemma_calls"] = len(calls)
        print(f"  Gemma called on {len(calls)}/{len(rows)} commands")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
