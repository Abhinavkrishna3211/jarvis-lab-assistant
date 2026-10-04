"""The guard rail: nothing the model says reaches the database or hardware unless this accepts it."""
from . import db
from .dates import resolve_due
from .llm import INTENTS

NEEDS_ITEM = {"FIND_TOOL", "TOOL_FOR_TASK", "FIND_COMPONENT", "LEND", "RETURN", "WHO_HAS", "STOCK"}
MAX_QTY = 200


class Invalid(Exception):
    """Rejected action. `have` and `item_name` let the reply say what is actually available."""

    def __init__(self, msg, item_name=None, have=None):
        super().__init__(msg)
        self.item_name, self.have = item_name, have


def validate(action, con, today):
    """Return a cleaned action dict or raise Invalid. Checks intent, item, qty, borrower, due date."""
    if not isinstance(action, dict):
        raise Invalid("not an object")
    intent = action.get("intent")
    if intent not in INTENTS or intent == "UNKNOWN":
        raise Invalid("unknown intent")
    clean = {"intent": intent}
    if intent in NEEDS_ITEM:
        item = db.get_item(con, str(action.get("item", "")))
        if not item:
            raise Invalid("item not in inventory")
        clean["item"] = item
        if intent == "FIND_TOOL" and item["kind"] != "tool":
            clean["intent"] = "FIND_COMPONENT"
        if intent == "FIND_COMPONENT" and item["kind"] != "component":
            clean["intent"] = "FIND_TOOL"
    qty = action.get("qty", 1)
    if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= MAX_QTY:
        raise Invalid("bad quantity")
    clean["qty"] = qty
    if intent in ("LEND", "RETURN"):
        b = str(action.get("borrower", "")).strip()
        if not b.isalpha() or len(b) > 20:
            raise Invalid("bad borrower")
        clean["borrower"] = b.capitalize()
    if intent == "LEND":
        due = resolve_due(action.get("due", ""), today)
        if not due:
            raise Invalid("bad due date")
        clean["due"] = due
        have = db.available(con, clean["item"])
        if qty > have:
            raise Invalid("not enough stock", clean["item"]["name"], have)
    return clean
