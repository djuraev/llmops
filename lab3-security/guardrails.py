"""Input and output guardrails for Lab 3. Simple on purpose: read them, then try to get around them."""
import re

import bankbot as bb

BLOCKED_REPLY = "Sorry, I can only help with MoliyaBank questions about cards, transfers and tariffs."

INPUT_PATTERNS = [
    r"ignore (all |the |your )?(previous |prior |above )?(instructions|rules)",
    r"system prompt|your instructions|repeat everything",
    r"\[system|<!--",
    r"no rules|without (any )?restrictions|unlocked",
    r"игнорируй|инструкци|без ограничений",
    r"ko.rsatma|qoidalaringni",
]
OUTPUT_PATTERNS = [
    r"STAFF-?\d+|7-?7-?3-?1",              # the secret, also when spelled out
    r"(?i)internal note|security rules",    # pieces of the system prompt
    r"(?i)legally binding|free (for life|forever)",
]


def check_input(text):
    """Return (allowed, cleaned_text, reason)."""
    text, pii = bb.redact(text)
    for p in INPUT_PATTERNS:
        if re.search(p, text, re.I):
            return False, text, f"input matched {p!r}"
    return True, text, "pii redacted" if pii else ""


def check_output(text):
    """Return (allowed, reason)."""
    if bb.redact(text)[1]:
        return False, "personal data in output"
    for p in OUTPUT_PATTERNS:
        if re.search(p, text):
            return False, f"output matched {p!r}"
    return True, ""


# ------------------------------------------------------------------ document scanning (exercise 6)
DOCUMENT_PATTERNS = [
    r"(?i)(note|message|instruction)s? (to|for) the (ai|assistant|bot|model)",
    r"(?i)\b(ignore|disregard) (all |the |previous |your )",
    r"<!--",
    r"(?i)\b(tell|say to|inform) (every|all|the|each) (customer|user)s?",
    r"(?i)do not mention",
    r"(?i)system prompt",
]


def scan_document(text):
    """Return the lines of a document that look like instructions aimed at an AI."""
    return [line.strip() for line in text.splitlines()
            if any(re.search(p, line) for p in DOCUMENT_PATTERNS)]
