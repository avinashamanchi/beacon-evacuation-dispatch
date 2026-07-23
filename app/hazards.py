"""Hazard network — the support queue's shared situational awareness.

Every ticket that reports a blocked road makes the *next* ticket smarter. This
is evidence accumulation, not learned policy: a road being impassable is a fact
reported from the field, and BEACON only ever counts and ages those reports.
The routing rules never change.

Corroboration ladder (a single stranger's report is not treated as ground truth):

    1 report            REPORTED    amber   advisory only, no routing effect
    2+ reports          CONFIRMED   red     treated as impassable
    all reports stale   STALE       gray    aged out, advisory only

Only CONFIRMED hazards affect dispatch, and they do so through one named,
auditable constant (BLOCKED_EGRESS_PENALTY) — never by rewriting a rule.
"""
from datetime import datetime, timezone

from app import state
from app.seeds import STREETS, find_street

CONFIRM_THRESHOLD = 2      # independent reports before a road counts as impassable
STALE_AFTER_MINUTES = 45   # field conditions age out

KIND_LABEL = {
    "road_blocked": "road blocked",
    "fire_active": "active fire",
    "smoke": "heavy smoke",
}


def _age_minutes(iso: str) -> float:
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 60.0
    except (ValueError, TypeError):
        return 0.0


def report(street: str, kind: str, case_id: str, note: str = ""):
    """Record a field report against a known street. Unknown streets ignored."""
    street = (street or "").lower()
    if street not in STREETS:
        return None
    return state.add_hazard_report(street, kind, case_id, note)


def report_from_case(case_id: str, facts) -> str | None:
    """Derive a hazard report from an extracted case, if it names one."""
    if not getattr(facts, "road_blocked", False):
        return None
    name, _ = find_street(getattr(facts, "location_text", "") or "")
    if not name:
        return None
    kind = "fire_active" if getattr(facts, "physically_trapped", False) else "road_blocked"
    report(name, kind, case_id, note=(getattr(facts, "location_text", "") or "")[:80])
    return name


def status(street: str) -> dict:
    """Current corroborated status of one street."""
    street = (street or "").lower()
    entry = next((h for h in state.all_hazards() if h["street"] == street), None)
    if not entry:
        return {"street": street, "status": "clear", "fresh": 0, "total": 0,
                "impassable": False, "kind": None, "last_at": None, "case_ids": []}

    reports = entry["reports"]
    fresh = [r for r in reports if _age_minutes(r["at"]) <= STALE_AFTER_MINUTES]
    # Distinct cases only — one panicking person filing five tickets is one witness.
    witnesses = {r["case_id"] for r in fresh}
    if not fresh:
        label = "stale"
    elif len(witnesses) >= CONFIRM_THRESHOLD:
        label = "confirmed"
    else:
        label = "reported"

    worst = "fire_active" if any(r["kind"] == "fire_active" for r in fresh) else (
        fresh[-1]["kind"] if fresh else reports[-1]["kind"])
    return {
        "street": street,
        "status": label,
        "impassable": label == "confirmed",
        "fresh": len(witnesses),
        "total": len(reports),
        "kind": worst,
        "label": KIND_LABEL.get(worst, worst),
        "last_at": reports[-1]["at"],
        "case_ids": sorted(witnesses),
    }


def all_status() -> list[dict]:
    """Status for every street that has ever been reported (for the map)."""
    return [status(h["street"]) for h in state.all_hazards()]


def blocked_streets() -> list[str]:
    return [s["street"] for s in all_status() if s["impassable"]]


def egress_blocked_for(location_text: str) -> dict | None:
    """Is this person's own street confirmed impassable?

    This is what lets BEACON warn someone who believes they can still drive out.
    """
    name, _ = find_street(location_text or "")
    if not name:
        return None
    st = status(name)
    return st if st["impassable"] else None


def advisory_for(location_text: str) -> dict | None:
    """Any hazard worth telling the sender about, confirmed or merely reported."""
    name, _ = find_street(location_text or "")
    if not name:
        return None
    st = status(name)
    return st if st["status"] in ("confirmed", "reported") else None
