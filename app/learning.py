"""Calibration engine — the part of BEACON that learns.

The boundary is the whole point:

  LEARNS      the constants inside the rules (how long an evacuation actually
              takes), and how accurately the model extracts facts.
  NEVER LEARNS the rules themselves, their order, or the routing decision.

Nothing here auto-applies. Everything is a *proposal with its evidence* that a
human approves, recorded in an audit trail. A learned routing policy trained on
historical dispatch would inherit historical bias — the exact failure this
project exists to argue against — so the router stays frozen and deterministic.

Observation kinds:
  override        a dispatcher re-routed a case (router/human disagreement)
  outcome         ground truth reported back: how long evacuation ACTUALLY took
  fact_correction a human corrected a fact the extractor got wrong
"""
import statistics

from app import router_rules, state

MIN_SAMPLES = 3          # never propose from fewer observations than this
DRIFT_THRESHOLD = 0.15   # only propose when reality differs by >15%
FACT_FIELDS = 11         # fields in ExtractedFacts


def sync_router() -> dict:
    """Apply approved calibration into the live router constants.

    This is the only path by which learning reaches the routing math, and it
    only ever rewrites a named integer a human signed off on.
    """
    overrides = state.get_calibration()["overrides"]
    for key, value in overrides.items():
        if key.startswith("evac_minutes."):
            mobility = key.split(".", 1)[1]
            if mobility in router_rules.EVAC_MINUTES:
                router_rules.EVAC_MINUTES[mobility] = int(value)
    return dict(router_rules.EVAC_MINUTES)


def record_override(case_id, from_path, to_path, reason=""):
    return state.record_observation({
        "kind": "override", "case_id": case_id,
        "from_path": from_path, "to_path": to_path, "reason": reason,
    })


def record_outcome(case_id, mobility=None, actual_evac_minutes=None, note=""):
    return state.record_observation({
        "kind": "outcome", "case_id": case_id, "mobility": mobility,
        "actual_evac_minutes": actual_evac_minutes, "note": note,
    })


def record_fact_correction(case_id, field, was, should_be):
    return state.record_observation({
        "kind": "fact_correction", "case_id": case_id,
        "field": field, "was": was, "should_be": should_be,
    })


def scorecard() -> dict:
    """How well is the extraction layer doing, measured against humans?"""
    obs = state.all_observations()
    reviewed = {o["case_id"] for o in obs if o["kind"] in ("outcome", "fact_correction")}
    corrected = {o["case_id"] for o in obs if o["kind"] == "fact_correction"}
    overrides = [o for o in obs if o["kind"] == "override"]

    by_field: dict[str, int] = {}
    for o in obs:
        if o["kind"] == "fact_correction":
            by_field[o["field"]] = by_field.get(o["field"], 0) + 1

    matrix: dict[str, int] = {}
    for o in overrides:
        key = f"{o['from_path']} -> {o['to_path']}"
        matrix[key] = matrix.get(key, 0) + 1

    n_reviewed = len(reviewed)
    clean = n_reviewed - len(corrected)
    return {
        "cases_reviewed": n_reviewed,
        "clean_extractions": clean,
        "extraction_accuracy": round(clean / n_reviewed, 3) if n_reviewed else None,
        "corrections_by_field": dict(sorted(by_field.items(), key=lambda kv: -kv[1])),
        "override_count": len(overrides),
        "override_matrix": dict(sorted(matrix.items(), key=lambda kv: -kv[1])),
        "observations": len(obs),
    }


def proposals() -> list[dict]:
    """Calibration proposals: constants that reality disagrees with.

    Median (not mean) so one catastrophic outlier can't yank the estimate.
    """
    obs = state.all_observations()
    buckets: dict[str, list[float]] = {}
    for o in obs:
        if o["kind"] == "outcome" and o.get("mobility") and o.get("actual_evac_minutes"):
            buckets.setdefault(o["mobility"], []).append(float(o["actual_evac_minutes"]))

    out = []
    for mobility, values in sorted(buckets.items()):
        if len(values) < MIN_SAMPLES:
            continue
        current = router_rules.EVAC_MINUTES.get(mobility)
        if not current:
            continue
        observed = round(statistics.median(values))
        drift = abs(observed - current) / current
        if drift <= DRIFT_THRESHOLD:
            continue
        out.append({
            "id": f"evac_minutes.{mobility}",
            "kind": "constant",
            "title": f"Evacuation estimate for '{mobility}'",
            "current": current,
            "proposed": observed,
            "delta": observed - current,
            "drift_pct": round(drift * 100),
            "samples": len(values),
            "observed_values": sorted(int(v) for v in values),
            "rationale": (
                f"{len(values)} reported evacuations for '{mobility}' ran a median of "
                f"{observed} min against an estimate of {current} min. "
                f"Under-estimating this makes time-to-impact look safer than it is."
            ),
        })
    return out


def rule_reviews() -> list[dict]:
    """Override patterns that a HUMAN should review — never auto-applied.

    When dispatchers keep overriding the same way, that is evidence a rule is
    wrong. BEACON surfaces it and stops. Changing a rule is a code change with
    a code review, not something the system does to itself at 3am.
    """
    obs = state.all_observations()
    matrix: dict[tuple, list[str]] = {}
    for o in obs:
        if o["kind"] == "override":
            matrix.setdefault((o["from_path"], o["to_path"]), []).append(o.get("reason", ""))

    RULE_FOR = {
        "fire_rescue": "R1", "accessible_shelter": "R3",
        "transport_assist": "R2", "standard": "R4/R5", "auto_answered": "R0",
    }
    out = []
    for (src, dst), reasons in sorted(matrix.items(), key=lambda kv: -len(kv[1])):
        if len(reasons) < MIN_SAMPLES:
            continue
        out.append({
            "id": f"rule.{src}.{dst}",
            "kind": "rule_review",
            "title": f"{len(reasons)} overrides moved {src} → {dst}",
            "suspect_rule": RULE_FOR.get(src, "?"),
            "count": len(reasons),
            "sample_reasons": [r for r in reasons if r][:3],
            "action": "HUMAN REVIEW — routing rules are never self-modified",
        })
    return out


def report() -> dict:
    return {
        "scorecard": scorecard(),
        "proposals": proposals(),
        "rule_reviews": rule_reviews(),
        "live_constants": dict(router_rules.EVAC_MINUTES),
        "calibration": state.get_calibration(),
        "guardrails": {
            "min_samples": MIN_SAMPLES,
            "drift_threshold_pct": round(DRIFT_THRESHOLD * 100),
            "auto_apply": False,
            "rules_mutable": False,
        },
    }


def approve(proposal_id: str, approved_by: str = "dispatcher"):
    """Apply a proposal a human approved. Returns None if it no longer holds."""
    match = next((p for p in proposals() if p["id"] == proposal_id), None)
    if not match:
        return None
    state.apply_calibration(
        proposal_id, match["proposed"],
        evidence={"samples": match["samples"], "observed": match["observed_values"],
                  "was": match["current"], "drift_pct": match["drift_pct"]},
        approved_by=approved_by,
    )
    sync_router()
    return match
