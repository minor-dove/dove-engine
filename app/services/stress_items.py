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


def plan_items(asked_counts: Dict[int, int], n: int = SESSION_ITEM_COUNT) -> List[int]:
    """Least-recently-asked rotation; always includes at least one positive (reverse) item."""
    ordered = sorted(ITEMS, key=lambda i: (asked_counts.get(i, 0), i))
    plan = ordered[:n]
    if not any(i in REVERSE_ITEMS for i in plan):
        rev = next(i for i in ordered if i in REVERSE_ITEMS)
        plan[-1] = rev
    return plan
