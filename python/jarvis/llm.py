"""Gemma 3 1B (App Lab llama.cpp runner) as the intent parser, plus the keyword baseline we compare it against."""
import json
import re
import urllib.request

from .matcher import best_item, score, words_to_digits

INTENTS = ["FIND_TOOL", "TOOL_FOR_TASK", "FIND_COMPONENT", "LEND", "RETURN", "OVERDUE", "WHO_HAS",
           "STOCK", "UNKNOWN"]

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"enum": INTENTS},
        "item": {"type": "string"},
        "qty": {"type": "integer"},
        "borrower": {"type": "string"},
        "due": {"type": "string"},
    },
    "required": ["intent"],
}

SYSTEM = (
    "You convert a spoken request in an electronics lab into ONE JSON object. Intents: "
    "FIND_TOOL (where is a named tool), TOOL_FOR_TASK (which tool for a job), FIND_COMPONENT "
    "(where/how many of a component), LEND (give items to a person), RETURN (person gives items back), "
    "OVERDUE (what is late), WHO_HAS (who holds an item), STOCK (how many left), UNKNOWN. "
    "Use item names ONLY from the candidate list, copied exactly. qty is an integer (default 1). "
    "borrower is a first name. due is a day word like Friday, tomorrow, or 'in 3 days'. "
    "Omit fields that do not apply. Reply with the JSON only."
)


def build_prompt(transcript, cands):
    lines = "\n".join(f"- {c['name']} ({c['kind']})" for c in cands) or "- (none)"
    return f"{SYSTEM}\n\nCandidates:\n{lines}\n\nRequest: {transcript}"


class LlamaServerLLM:
    """Gemma 3 1B served by App Lab's llama.cpp runner (the arduino:llm brick), OpenAI-compatible API.
    The JSON schema constrains decoding, so the reply is always one parseable action."""

    def __init__(self, base_url="http://llamacpp-models-runner:9999/v1", model="gemma-3-1b-it-Q4_0",
                 timeout=90):
        self.url, self.model, self.timeout = base_url.rstrip("/") + "/chat/completions", model, timeout

    def parse(self, transcript, cands):
        body = json.dumps({
            "model": self.model, "temperature": 0, "max_tokens": 60,
            "messages": [{"role": "user", "content": build_prompt(transcript, cands)}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "action", "schema": ACTION_SCHEMA}},
        }).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            text = json.loads(r.read())["choices"][0]["message"]["content"]
        return json.loads(text)


class HybridLLM:
    """Keyword rules first (instant). Gemma only when the rules give up AND the request names an item
    or a known use of one (matcher score >= 0.7). On the UNO Q Gemma takes about 28 s per request and
    invents items for small talk, so it only sees requests it can help with. See docs/measurements.md."""

    def __init__(self, llm, on_slow=None):
        self.llm, self.on_slow = llm, on_slow

    def parse(self, transcript, cands):
        out = keyword_parse(transcript, cands)
        if out["intent"] != "UNKNOWN" or not any(score(transcript, c) >= 0.7 for c in cands):
            return out
        if self.on_slow:
            self.on_slow()
        return self.llm.parse(transcript, cands)


class ScriptedLLM:
    """Test double: returns canned JSON per transcript so engine logic is testable off-board."""

    def __init__(self, table):
        self.table = table

    def parse(self, transcript, cands):
        return self.table.get(transcript.lower().strip(" .?!"), {"intent": "UNKNOWN"})


# ---------------------------------------------------------------- keyword baseline
_NAME = r"([A-Z][a-z]+)"
_TASK_CUE = re.compile(r"\b(need|use|which tool|what tool|something to|something for|how (do|can) i"
                       r"|(want|have|trying|going|got) to)\b")
_STOP = {"a", "an", "the", "to", "for", "from", "of", "and", "in", "on", "with"}


def _task_tool(tl, items):
    """The tool whose listed use best matches the request ("measure the diameter" -> vernier caliper).
    A use counts when all its words appear (stems: "measuring" matches "measure"), or at least two do."""
    said = re.findall(r"[a-z]+", tl)
    best, best_key = None, (0, 0)
    for it in items:
        if it["kind"] != "tool":
            continue
        for use in filter(None, (it["uses"] or "").split(",")):
            words = [w for w in use.split() if w not in _STOP]
            hit = sum(any(s.startswith(w[:5]) for s in said) for w in words)
            key = (hit / len(words), hit)
            if (hit == len(words) or hit >= 2) and key > best_key:
                best, best_key = it, key
    return best


def keyword_parse(transcript, items):
    """Deliberately simple rules. Gets the same fuzzy item matcher as Gemma so the comparison is fair."""
    t = words_to_digits(transcript)
    tl = t.lower()
    item = best_item(transcript, items)
    out = {"intent": "UNKNOWN"}
    if item:
        out["item"] = item["name"]
    m = re.search(r"\b(\d+)\b", tl)
    out["qty"] = int(m.group(1)) if m else 1
    if "overdue" in tl or "late" in tl:
        out["intent"] = "OVERDUE"
    elif re.search(r"\blend|give|loan\b", tl):
        out["intent"] = "LEND"
        mb = re.search(r"\bto ([A-Za-z]+)", transcript)
        if mb:
            out["borrower"] = mb.group(1).capitalize()
        md = re.search(r"\b(?:till|until|by) (\w+(?: \w+)?)", tl)
        if md:
            out["due"] = md.group(1)
    elif re.search(r"returned|brought back|gave back|back with", tl):
        out["intent"] = "RETURN"
        mb = re.match(_NAME, transcript.strip())
        if mb:
            out["borrower"] = mb.group(1)
    elif re.search(r"who has|who's got|who got", tl):
        out["intent"] = "WHO_HAS"
    elif re.search(r"how many|stock|left", tl):
        out["intent"] = "STOCK"
    elif re.search(r"\b(where|point|show me|find|locate)\b", tl) and item:
        out["intent"] = "FIND_TOOL" if item["kind"] == "tool" else "FIND_COMPONENT"
    elif _TASK_CUE.search(tl) and _task_tool(tl, items):
        out["intent"], out["item"] = "TOOL_FOR_TASK", _task_tool(tl, items)["name"]
    elif re.search(r"\bneed|use|cut|measure|solder\b", tl) and item and item["kind"] == "tool":
        out["intent"] = "TOOL_FOR_TASK"
    return out
