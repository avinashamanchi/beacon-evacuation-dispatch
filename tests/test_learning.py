"""Calibration engine tests — especially the boundary it must never cross."""
import pytest

from app import learning, router_rules, state


@pytest.fixture(autouse=True)
def clean():
    state.reset_learning()
    router_rules.EVAC_MINUTES.update(
        {"ambulatory": 10, "limited": 30, "non_ambulatory": 45, "unknown": 30})
    yield
    state.reset_learning()
    router_rules.EVAC_MINUTES.update(
        {"ambulatory": 10, "limited": 30, "non_ambulatory": 45, "unknown": 30})


# --- proposals ---------------------------------------------------------------
def test_no_proposal_below_min_samples():
    for _ in range(learning.MIN_SAMPLES - 1):
        learning.record_outcome("c1", "non_ambulatory", 70)
    assert learning.proposals() == []


def test_no_proposal_when_reality_matches_estimate():
    for _ in range(5):
        learning.record_outcome("c", "non_ambulatory", 46)  # ~2% drift
    assert learning.proposals() == []


def test_proposal_when_reality_drifts():
    for v in (62, 70, 58, 66):
        learning.record_outcome("c", "non_ambulatory", v)
    props = learning.proposals()
    assert len(props) == 1
    p = props[0]
    assert p["id"] == "evac_minutes.non_ambulatory"
    assert p["current"] == 45
    assert p["proposed"] == 64        # median of 58,62,66,70
    assert p["samples"] == 4


def test_median_resists_single_outlier():
    for v in (46, 47, 45, 600):       # one catastrophic outlier
        learning.record_outcome("c", "non_ambulatory", v)
    # median stays ~46 => within threshold => no proposal
    assert learning.proposals() == []


# --- approval is the only path to a constant change --------------------------
def test_proposal_does_not_auto_apply():
    for v in (62, 70, 58):
        learning.record_outcome("c", "non_ambulatory", v)
    learning.proposals()
    assert router_rules.EVAC_MINUTES["non_ambulatory"] == 45  # untouched


def test_approval_updates_constant_and_audits():
    for v in (62, 70, 58):
        learning.record_outcome("c", "non_ambulatory", v)
    applied = learning.approve("evac_minutes.non_ambulatory", approved_by="chief")
    assert applied["proposed"] == 62
    assert router_rules.EVAC_MINUTES["non_ambulatory"] == 62
    audit = state.get_calibration()["audit"]
    assert audit[0]["approved_by"] == "chief"
    assert audit[0]["from"] is None and audit[0]["to"] == 62
    assert audit[0]["evidence"]["samples"] == 3


def test_approving_unknown_proposal_returns_none():
    assert learning.approve("evac_minutes.nope") is None


def test_sync_router_reapplies_on_boot():
    state.apply_calibration("evac_minutes.limited", 41, {}, "chief")
    router_rules.EVAC_MINUTES["limited"] = 30      # simulate fresh process
    learning.sync_router()
    assert router_rules.EVAC_MINUTES["limited"] == 41


# --- the guardrail: rules are never self-modified ----------------------------
def test_override_pattern_becomes_review_not_a_rule_change():
    for _ in range(4):
        learning.record_override("c", "accessible_shelter", "transport_assist", "no lift van")
    reviews = learning.rule_reviews()
    assert len(reviews) == 1
    assert reviews[0]["suspect_rule"] == "R3"
    assert reviews[0]["count"] == 4
    assert "HUMAN REVIEW" in reviews[0]["action"]
    # crucially: no approvable proposal was created from override pressure
    assert all(p["kind"] == "constant" for p in learning.proposals())


def test_overrides_never_produce_constant_proposals():
    for _ in range(20):
        learning.record_override("c", "transport_assist", "standard", "was fine")
    assert learning.proposals() == []


def test_report_declares_guardrails():
    g = learning.report()["guardrails"]
    assert g["auto_apply"] is False
    assert g["rules_mutable"] is False


# --- extraction scorecard ----------------------------------------------------
def test_scorecard_measures_extraction_accuracy():
    learning.record_outcome("a", "ambulatory", 11)
    learning.record_outcome("b", "limited", 29)
    learning.record_fact_correction("b", "medical_equipment", "none", "oxygen")
    s = learning.scorecard()
    assert s["cases_reviewed"] == 2
    assert s["clean_extractions"] == 1
    assert s["extraction_accuracy"] == 0.5
    assert s["corrections_by_field"]["medical_equipment"] == 1


def test_scorecard_empty_is_safe():
    s = learning.scorecard()
    assert s["cases_reviewed"] == 0
    assert s["extraction_accuracy"] is None
