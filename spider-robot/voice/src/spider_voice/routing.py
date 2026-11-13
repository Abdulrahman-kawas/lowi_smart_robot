"""The router prompt, its JSON schema, and the only code allowed to interpret its output."""

from __future__ import annotations

import json

from .grammar import MOTION_ACTS, MOVE_ACTS, ROUTER_ACTS, acts_in, has_negation
from .interfaces import RouterDecision

MAX_SAY_CHARS = 60
FALLBACK_SAY = "ما فهمت، عيد لو سمحت"

# Kept short on purpose: the model is a small router with a small context.
SYSTEM_PROMPT = (
    "You control a small walking robot. Reply with JSON only. "
    "act is the movement the user asked for, otherwise none. "
    "say is a short reply in Arabic, at most 10 words."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "act": {"type": "string", "enum": list(ROUTER_ACTS)},
        "say": {"type": "string", "maxLength": MAX_SAY_CHARS},
    },
    "required": ["act", "say"],
}

# Measured with the real LFM2.5-350M tokenizer: at worst about 0.78 tokens per Arabic character, so
# 60 characters is about 47 tokens, plus 12 for the JSON. 80 leaves a margin; bench S1 confirms it.
NUM_PREDICT = 80
NUM_CTX = 512
TEMPERATURE = 0.1


def parse_decision(raw: str) -> RouterDecision:
    """Output that does not parse means no action. A truncated reply is not a command."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return RouterDecision("none", FALLBACK_SAY)
    if not isinstance(data, dict):
        return RouterDecision("none", FALLBACK_SAY)
    act, say = data.get("act"), data.get("say")
    if act not in ROUTER_ACTS or not isinstance(say, str):
        return RouterDecision("none", FALLBACK_SAY)
    return RouterDecision(act, say.strip()[:MAX_SAY_CHARS])


def cross_check(decision: RouterDecision, transcript: str) -> RouterDecision:
    """A motion is accepted only if the owner's own words name it and do not negate it.

    The router has no move acts, so a move cannot come from it; if one ever did, it is checked
    the same way as a walk.
    """
    if decision.act in (MOTION_ACTS | MOVE_ACTS) and (
        decision.act not in acts_in(transcript) or has_negation(transcript)
    ):
        return RouterDecision("none", decision.say)
    return decision
