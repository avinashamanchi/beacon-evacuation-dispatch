"""THE deterministic dispatch router.

Design principle, non-negotiable: the LLM extracts facts; this plain Python
function decides. The rule order below IS the priority order — the first rule
whose condition holds fires. The model never touches this function.
"""

EVAC_MINUTES = {"ambulatory": 10, "limited": 30, "non_ambulatory": 45, "unknown": 30}
NO_VEHICLE_PENALTY = 15


def evac_time_needed(facts) -> int:
    t = EVAC_MINUTES[facts.mobility]
    if not facts.has_vehicle:
        t += NO_VEHICLE_PENALTY
    return t


def route(facts, fire_eta_minutes: int):
    """Deterministic dispatch. The LLM never touches this function."""
    if facts.is_informational_only and not facts.physically_trapped:
        return "auto_answered", "R0: informational only -> Guide auto-answer", None

    evac_need = evac_time_needed(facts)
    tti = fire_eta_minutes - evac_need
    eq = {"fire_eta": fire_eta_minutes, "evac_need": evac_need, "time_to_impact": tti}

    if facts.physically_trapped or facts.injuries_reported:
        return "fire_rescue", "R1: trapped or injured -> fire/rescue asset", eq
    if facts.already_evacuated:
        if facts.medical_equipment != "none":
            return "accessible_shelter", "R3: evacuated + medical need -> capable shelter", eq
        return "standard", "R4: evacuated, no special need", eq
    if not facts.can_self_evacuate or tti < 0:
        return "transport_assist", "R2: cannot self-evacuate before fire arrival -> transport", eq
    return "standard", "R5: can self-evacuate in time", eq
