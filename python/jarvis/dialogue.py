"""JARVIS persona. Code fills {blanks} from the database and picks one variation at random.
Rules: calm British butler, under 20 words, dry wit ~1 in 5, never aimed at a student, never bluffs."""
import random

BANK = {
    "wake": ["Good {part}, {name}. What do you need?",
             "Good {part}, {name}. The lab is at your disposal.",
             "Good {part}, {name}. All systems online. How can I help?",
             "At your service, {name}. Good {part}."],
    "tool_found": ["The {tool} is on the wall, {position}. I've marked it.",
                   "{tool}, {position}. Follow the red dot.",
                   "Marked. Do return the {tool} to the same hook, sir.",
                   "There. The {tool}, right where it belongs."],
    "tool_task": ["For that, I'd recommend the {tool}. Marking it now.",
                  "The {tool} is the right choice. It's {position}.",
                  "A {tool} will do nicely. I've lit the way."],
    "tool_loan": ["The {tool} is currently with {borrower}, since {date}.",
                  "I'm afraid the {tool} is out with {borrower}. Due back {due}."],
    "comp_found": ["{item}: {qty} in stock. The box is lit.",
                   "{qty} {item} available. Look for the glowing box.",
                   "Box {box}, {qty} left. Lit for you."],
    "low_stock": ["A note: only {qty} {item} left.", "{item} running low. {qty} remaining."],
    "out_stock": ["We're out of {item}, I'm afraid.", "The {item} box is empty."],
    "short_stock": ["I only have {have} {item} available, I'm afraid.",
                    "Only {have} {item} on the shelf at the moment."],
    "lend_confirm": ["Lending {qty} {item} to {borrower} until {due}. Shall I log it?",
                     "To confirm: {borrower} takes {qty} {item}, back by {due}. Yes?"],
    "lend_saved": ["Logged. I'll keep an eye on its return.",
                   "Done. {borrower} now holds {qty} {item}.",
                   "Recorded. Good luck with the project, {borrower}."],
    "cancelled": ["Cancelled. Nothing logged.", "Very well, I'll forget I heard that."],
    "return_confirm": ["{borrower} returns {qty} {item}. Shall I log it?"],
    "return_saved": ["{qty} {item} returned. Stock is {total}.",
                     "Thank you, {borrower}. All accounted for."],
    "no_loan": ["I have no open loan of {item} for {borrower}."],
    "overdue": ["{n} items are overdue. The oldest is {item}, with {borrower} since {date}.",
                "Overdue: {list}."],
    "no_overdue": ["Everything is accounted for. A rare and pleasant state of affairs.",
                   "No overdue items. The lab thanks you."],
    "who_has": ["{borrower} has the {item}, since {date}.", "The {item} is with {borrower}, due {due}."],
    "nobody": ["Nobody. The {item} is on the shelf."],
    "not_stocked": ["I'm afraid we don't have that, {name}.", "That's not something we stock, sir."],
    "unclear": ["My apologies, I didn't catch that. Once more?", "Could you repeat that, sir?",
                "I heard words, but not a request. Again, please."],
    "error": ["Something went wrong on my side. Try again in a moment."],
    "thanks": ["Always a pleasure.", "Happy to help, sir."],
}


def say(key, rng=random, **fields):
    fields.setdefault("name", "sir")
    return rng.choice(BANK[key]).format(**fields)
