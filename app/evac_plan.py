"""Deterministic evacuation guidance for the person who sent the message.

"You can't FaceTime the firefighters." So the sender gets a concrete plan back:
what is blocked, which way is still open, whether to move or stay put, and what
has already been dispatched to them.

This is plain arithmetic and set logic over the hazard network — NOT a language
model improvising directions. Telling someone which way to run is exactly the
kind of decision that must be auditable and reproducible.

The fire origin sits at the map's north-east, so safety is broadly south-west;
"away from the fire" is computed, not narrated.
"""
from app import hazards
from app.seeds import STREETS

FIRE_ORIGIN = {"x": 95.0, "y": 5.0}   # north-east corner, matches the map


def _bearing_label(dx: float, dy: float) -> str:
    ns = "north" if dy < -3 else ("south" if dy > 3 else "")
    ew = "west" if dx < -3 else ("east" if dx > 3 else "")
    return (ns + ("-" if ns and ew else "") + ew) or "nearby"


def street_label(name: str) -> str:
    """Title-case without mangling apostrophes (Miner's Bend, not Miner'S Bend)."""
    return " ".join(w[:1].upper() + w[1:] for w in (name or "").split())


def _dist(a, b):
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


def safest_route(from_street: str, blocked: set[str]):
    """Nearest street that is not blocked and is further from the fire origin."""
    here = STREETS.get(from_street)
    if not here:
        return None
    here_risk = _dist(here, FIRE_ORIGIN)
    best, best_d = None, float("inf")
    for name, c in STREETS.items():
        if name == from_street or name in blocked:
            continue
        # must gain meaningful distance from the fire, not a token step
        if _dist(c, FIRE_ORIGIN) < here_risk * 1.12:
            continue
        d = _dist(here, c)
        if d < best_d:
            best, best_d = name, d
    if not best:
        return None
    tgt = STREETS[best]
    return {"street": best,
            "bearing": _bearing_label(tgt["x"] - here["x"], tgt["y"] - here["y"]),
            "label": street_label(best)}


def build(facts, dispatch_path: str, equation: dict | None) -> dict:
    """Assemble the plan. Every field is derived, none of it is generated text."""
    blocked = set(hazards.blocked_streets())
    from app.seeds import find_street
    here, _ = find_street(getattr(facts, "location_text", "") or "")
    tti = (equation or {}).get("time_to_impact")

    steps: list[str] = []
    if dispatch_path in ("fire_rescue", "needs_human_review"):
        headline = "Stay where you are. Rescue is coming to you."
        steps.append("Do not attempt to drive out — crews are routing to your location.")
        steps.append("Move to the side of the structure furthest from the fire and stay low.")
        steps.append("If you can do so safely, make yourself visible from the road.")
    elif dispatch_path == "transport_assist":
        headline = "Do not attempt to leave on your own. Transport is dispatched."
        if tti is not None and tti < 0:
            steps.append(f"The fire is expected before you could finish evacuating "
                         f"({abs(tti)} min short). Waiting for the vehicle is the safer option.")
        steps.append("Gather medication and mobility equipment by the door now.")
        steps.append("Leave an exterior light on so the crew can identify the address.")
    elif dispatch_path == "accessible_shelter":
        headline = "A shelter with medical capability is being arranged."
        steps.append("Bring your equipment, chargers, and a list of medications.")
    else:
        headline = "You can still leave under your own power. Go now."
        if tti is not None:
            steps.append(f"Estimated margin: {tti} minutes. Do not wait for an official knock.")

    route = safest_route(here, blocked) if here else None
    if here and here in blocked:
        steps.insert(0, f"Your own street is reported impassable — do not use it.")
    if blocked:
        steps.append("Confirmed impassable: "
                     + ", ".join(sorted(street_label(s) for s in blocked)) + ".")
    if route and dispatch_path == "standard":
        steps.append(f"Clearest route away from the fire: head {route['bearing']} "
                     f"toward {route['label']}.")

    return {
        "headline": headline,
        "steps": steps,
        "blocked_routes": sorted(blocked),
        "recommended_route": route,
        "located_at": here,
        "time_to_impact": tti,
        "basis": "deterministic — hazard network + evacuation arithmetic, no generated directions",
    }
