"""Thread-safe in-memory store plus fire perimeter state. No database."""
import threading
from datetime import datetime, timezone

from app.config import FIRE_ETA_MINUTES

_lock = threading.RLock()
_cases: dict[str, dict] = {}
_fire = {"eta_minutes": FIRE_ETA_MINUTES, "perimeter_step": 0}
_escalations: list[dict] = []

MAX_PERIMETER_STEP = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_case(case: dict) -> dict:
    with _lock:
        _cases[case["id"]] = case
    return case


def get_case(case_id: str):
    with _lock:
        c = _cases.get(case_id)
        return dict(c) if c else None


def update_case(case_id: str, **changes):
    with _lock:
        c = _cases.get(case_id)
        if c is not None:
            c.update(changes)
            return dict(c)
        return None


def add_timeline(case_id: str, event: str):
    with _lock:
        c = _cases.get(case_id)
        if c is not None:
            c["timeline"].append({"at": now_iso(), "event": event})


def record_escalation(entry: dict):
    with _lock:
        _escalations.insert(0, entry)
        del _escalations[10:]


def recent_escalations():
    with _lock:
        return [dict(e) for e in _escalations[:5]]


def all_cases() -> list[dict]:
    with _lock:
        return [dict(c) for c in sorted(
            _cases.values(), key=lambda c: c["created_at"], reverse=True
        )]


def get_fire() -> dict:
    with _lock:
        return dict(_fire)


def advance_fire() -> dict:
    with _lock:
        _fire["eta_minutes"] = max(0, _fire["eta_minutes"] - 3)
        _fire["perimeter_step"] = min(MAX_PERIMETER_STEP, _fire["perimeter_step"] + 1)
        eta = _fire["eta_minutes"]
        # Re-compute time_to_impact for every open case as the fire closes in.
        for c in _cases.values():
            eq = c.get("equation")
            if eq:
                eq["fire_eta"] = eta
                eq["time_to_impact"] = eta - eq["evac_need"]
        return dict(_fire)


def counts() -> dict:
    with _lock:
        result: dict[str, int] = {}
        for c in _cases.values():
            p = c["dispatch_path"]
            result[p] = result.get(p, 0) + 1
        return result


# --- Learning substrate -----------------------------------------------------
# Observations and approved calibration deliberately SURVIVE reset_all(): a new
# incident does not erase what previous incidents taught us.
_observations: list[dict] = []
_calibration = {"overrides": {}, "audit": []}


def record_observation(obs: dict):
    with _lock:
        obs = dict(obs)
        obs["at"] = now_iso()
        _observations.append(obs)
        return obs


def all_observations() -> list[dict]:
    with _lock:
        return [dict(o) for o in _observations]


def get_calibration() -> dict:
    with _lock:
        return {"overrides": dict(_calibration["overrides"]),
                "audit": [dict(a) for a in _calibration["audit"]]}


def apply_calibration(key: str, value: int, evidence: dict, approved_by: str):
    """Human-approved constant change. Recorded with its evidence — a signed
    proposal, never a silent update."""
    with _lock:
        before = _calibration["overrides"].get(key)
        _calibration["overrides"][key] = value
        _calibration["audit"].insert(0, {
            "at": now_iso(), "key": key, "from": before, "to": value,
            "approved_by": approved_by, "evidence": evidence,
        })
        return dict(_calibration["overrides"])


def reset_learning():
    with _lock:
        _observations.clear()
        _calibration["overrides"].clear()
        _calibration["audit"].clear()


_sim = {"running": False}


def reset_all():
    """Fresh incident: clear cases + escalations, restore fire to start."""
    with _lock:
        _cases.clear()
        _escalations.clear()
        _fire["eta_minutes"] = FIRE_ETA_MINUTES
        _fire["perimeter_step"] = 0


def sim_running() -> bool:
    with _lock:
        return _sim["running"]


def set_sim(running: bool):
    with _lock:
        _sim["running"] = running


def known_ticket_ids() -> set:
    with _lock:
        return {c["zendesk_ticket_id"] for c in _cases.values() if c.get("zendesk_ticket_id")}
