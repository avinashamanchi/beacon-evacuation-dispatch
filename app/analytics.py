"""Deterministic message analytics for BEACON.

panic_score is the demo's counter-metric: a plain, auditable measure of how
URGENT a message *sounds*. BEACON computes it, displays it, and pointedly does
NOT route on it — the scatter on the dashboard shows tone and need are
uncorrelated. No ML, no LLM: the same message always scores the same.
"""
import re

_URGENCY_WORDS = re.compile(
    r"\b(now|urgent|urgently|help|please|asap|emergency|panic|panicking|"
    r"hurry|immediately|right now|dying|screaming|begging)\b",
    re.IGNORECASE,
)


def panic_score(message: str) -> int:
    """0–100. Exclamation marks, shouting caps, stacked ?s, urgency lexicon.
    Deliberately naive — it models what a tone-based queue would rank on."""
    if not message:
        return 0
    exclaims = message.count("!")
    double_q = len(re.findall(r"\?{2,}", message))
    urgent_hits = len(_URGENCY_WORDS.findall(message))
    alpha = [c for c in message if c.isalpha()]
    caps_ratio = (sum(1 for c in alpha if c.isupper()) / len(alpha)) if alpha else 0.0
    score = exclaims * 9 + double_q * 8 + urgent_hits * 11 + caps_ratio * 55
    return min(100, round(score))


# Priority weight for the *need* ordering (what BEACON actually routes on).
NEED_PRIORITY = {
    "fire_rescue": 3,
    "needs_human_review": 3,
    "transport_assist": 2,
    "accessible_shelter": 1,
}


def attach_ranks(cases: list[dict]) -> None:
    """Mutate the case dicts (already copies) with tone_rank and need_rank.

    tone_rank — position in a queue sorted by how urgent the message SOUNDS.
    need_rank — position in BEACON's queue: dispatch priority, then least
    time-to-impact first. The gap between the two is each case's counterfactual:
    how far a tone-based queue would have mis-served it.
    """
    by_tone = sorted(cases, key=lambda c: (-(c.get("panic_score") or 0), c["created_at"]))
    for i, c in enumerate(by_tone):
        c["tone_rank"] = i + 1

    def need_key(c):
        eq = c.get("equation") or {}
        tti = eq.get("time_to_impact")
        return (
            -NEED_PRIORITY.get(c["dispatch_path"], 0),
            tti if tti is not None else 999,
            c["created_at"],
        )

    by_need = sorted(cases, key=need_key)
    for i, c in enumerate(by_need):
        c["need_rank"] = i + 1


def compute_metrics(cases: list[dict], crew_counts: dict) -> dict:
    total = len(cases)
    flagged = [c for c in cases if c["dispatch_path"] in NEED_PRIORITY]
    auto = sum(1 for c in cases if c["dispatch_path"] == "auto_answered")
    ms_values = sorted(c["processing_ms"] for c in cases if c.get("processing_ms") is not None)
    median_ms = ms_values[len(ms_values) // 2] if ms_values else 0
    lanes = {}
    for path in ("fire_rescue", "transport_assist", "accessible_shelter"):
        active = sum(
            1 for c in cases
            if c.get("status") != "resolved"
            and (c["dispatch_path"] == path
                 or (path == "fire_rescue" and c["dispatch_path"] == "needs_human_review"))
        )
        capacity = int(crew_counts.get(path, 0))
        lanes[path] = {"active": active, "capacity": capacity,
                       "saturated": capacity > 0 and active > capacity}
    return {
        "total": total,
        "flagged": len(flagged),
        "deflected_pct": round(100 * auto / total) if total else 0,
        "median_ms": median_ms,
        "lanes": lanes,
    }
