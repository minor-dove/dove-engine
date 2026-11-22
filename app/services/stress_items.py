"""
Adapted PSS-10 item bank (Cohen et al. 1983), re-worded for a same-day recall window.
NOT a validated instrument: results are a wellbeing indicator, never a diagnosis.
Answer scale (value): 0 = not at all, 1 = a little, 2 = sometimes, 3 = fairly often, 4 = very often.
Reverse-scored items (positive wording): 4, 5, 7, 8.
"""

from typing import Dict, List, Optional, Tuple

REVERSE_ITEMS = {4, 5, 7, 8}

# item_id -> (canonical question, short topic)
ITEMS: Dict[int, str] = {
    1: "Today, how often did something unexpected happen that upset you?",
    2: "Today, how often did it feel like you couldn't control the important things?",
    3: "Today, how often did you feel nervous or stressed?",
    4: "Today, how often did you feel confident you could handle your personal problems?",
    5: "Today, how often did you feel that things were going your way?",
    6: "Today, how often did it feel like you couldn't cope with everything you had to do?",
    7: "Today, how often were you able to control irritations in your life?",
    8: "Today, how often did you feel on top of things?",
    9: "Today, how often did you get angry about things outside your control?",
    10: "Today, how often did difficulties pile up so high that you felt you couldn't overcome them?",
}

# Same ten items, but the time window is a parameter so a question is about the stretch of time it is
# asked in ("so far this morning", "since we last talked"), not always "today". Meaning is unchanged.
ITEM_STEMS: Dict[int, str] = {
    1: "how often did something unexpected happen that upset you?",
    2: "how often did it feel like you couldn't control the important things?",
    3: "how often did you feel nervous or stressed?",
    4: "how often did you feel confident you could handle your personal problems?",
    5: "how often did you feel that things were going your way?",
    6: "how often did it feel like you couldn't cope with everything you had to do?",
    7: "how often were you able to control irritations in your life?",
    8: "how often did you feel on top of things?",
    9: "how often did you get angry about things outside your control?",
    10: "how often did difficulties pile up so high that you felt you couldn't overcome them?",
}

# Which items fit which part of the day best (retrospective vs. forward-looking). Used only to choose
# WHICH items to ask when; never changes how an answer is scored.
DAYPART_AFFINITY: Dict[str, set] = {
    "morning": {2, 4, 5, 8, 3},
    "afternoon": {1, 3, 6, 7, 8},
    "evening": {1, 6, 9, 10, 5},
    "night": {3, 5, 8, 10, 2},
}


def item_question(item_id: int, window: str = "today") -> str:
    """Canonical wording of an item for a time window, e.g. 'Since we last talked, how often ...?'"""
    w = (window or "today").strip()
    return f"{w[:1].upper()}{w[1:]}, {ITEM_STEMS[item_id]}"


MIN_VALID_ITEMS = 3
SESSION_ITEM_COUNT = 5

# Numeric score ranges (owner preference: report numbers, not labels).
BANDS = [(33.0, "0-33"), (66.0, "34-66"), (100.0, "67-100")]


def band_for(score: float) -> str:
    for upper, name in BANDS:
        if score <= upper:
            return name
    return "67-100"


def item_stress_value(item_id: int, value: int) -> int:
    """Stress contribution 0-4 (reverse-scores positive items)."""
    return 4 - value if item_id in REVERSE_ITEMS else value


def compute_score(answers: List[Tuple[int, Optional[int]]]) -> Optional[float]:
    """
    answers: (item_id, value 0-4 or None). Returns 0-100, or None if fewer than
    MIN_VALID_ITEMS scorable answers. Takes ONLY answers: emotion data can't influence it.
    """
    vals = [item_stress_value(i, v) for i, v in answers if v is not None and 0 <= v <= 4]
    if len(vals) < MIN_VALID_ITEMS:
        return None
    return round(sum(vals) / len(vals) / 4 * 100, 1)


def plan_items(asked_counts: Dict[int, int], n: int = SESSION_ITEM_COUNT, daypart: Optional[str] = None,
               asked_today: Optional[Dict[int, int]] = None,
               drop_rates: Optional[Dict[int, float]] = None) -> List[int]:
    """
    Choose the items for a session. Priority (lower sorts first):
      least-asked overall  +  3x already asked today (don't repeat within a day)
      - 0.75 if it suits this part of the day  +  1.5 x how often the person's answer was unusable
    Always includes at least one positive (reverse-scored) item. Deterministic.
    """
    asked_today = asked_today or {}
    drop_rates = drop_rates or {}
    fit = DAYPART_AFFINITY.get(daypart or "", set())

    def prio(i: int):
        return (asked_counts.get(i, 0) + 3.0 * asked_today.get(i, 0)
                - (0.75 if i in fit else 0.0) + 1.5 * drop_rates.get(i, 0.0), i)

    ordered = sorted(ITEMS, key=prio)
    plan = ordered[:n]
    if not any(i in REVERSE_ITEMS for i in plan):
        rev = next(i for i in ordered if i in REVERSE_ITEMS)
        plan[-1] = rev
    return plan
