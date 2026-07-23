"""The deterministic router is the product's spine — every rule gets a test."""
import os

os.environ.setdefault("DEMO_MODE", "true")

from app.extraction import ExtractedFacts
from app.router_rules import EVAC_MINUTES, NO_VEHICLE_PENALTY, evac_time_needed, route

FIRE = 18


def facts(**kw):
    return ExtractedFacts(**kw)


def test_r0_informational_auto_answers():
    path, rule, eq = route(facts(is_informational_only=True), FIRE)
    assert path == "auto_answered" and rule.startswith("R0") and eq is None


def test_r0_trapped_overrides_informational():
    # A message can ask a question AND report being trapped — danger wins.
    path, rule, _ = route(facts(is_informational_only=True, physically_trapped=True), FIRE)
    assert path == "fire_rescue" and rule.startswith("R1")


def test_r1_trapped():
    path, rule, eq = route(facts(physically_trapped=True), FIRE)
    assert path == "fire_rescue" and eq["fire_eta"] == FIRE


def test_r1_injured():
    path, rule, _ = route(facts(injuries_reported=True), FIRE)
    assert path == "fire_rescue"


def test_r2_non_ambulatory_no_vehicle():
    f = facts(mobility="non_ambulatory", has_vehicle=False, can_self_evacuate=False)
    path, rule, eq = route(f, FIRE)
    assert path == "transport_assist"
    assert eq["evac_need"] == EVAC_MINUTES["non_ambulatory"] + NO_VEHICLE_PENALTY
    assert eq["time_to_impact"] == FIRE - 60


def test_r2_negative_margin_even_if_willing():
    # Can self-evacuate but the math says they won't make it -> transport.
    f = facts(mobility="non_ambulatory", has_vehicle=True, can_self_evacuate=True)
    path, _, eq = route(f, FIRE)
    assert path == "transport_assist" and eq["time_to_impact"] < 0


def test_r3_evacuated_with_medical_need():
    f = facts(already_evacuated=True, medical_equipment="oxygen", mobility="ambulatory")
    path, rule, _ = route(f, FIRE)
    assert path == "accessible_shelter" and rule.startswith("R3")


def test_r4_evacuated_no_need():
    f = facts(already_evacuated=True, medical_equipment="none", mobility="ambulatory")
    path, rule, _ = route(f, FIRE)
    assert path == "standard" and rule.startswith("R4")


def test_r5_ambulatory_in_time():
    path, rule, eq = route(facts(mobility="ambulatory"), FIRE)
    assert path == "standard" and eq["time_to_impact"] == FIRE - EVAC_MINUTES["ambulatory"]


def test_priority_trapped_beats_evacuated():
    f = facts(physically_trapped=True, already_evacuated=True)
    path, _, _ = route(f, FIRE)
    assert path == "fire_rescue"


def test_evac_time_vehicle_penalty():
    with_car = evac_time_needed(facts(mobility="limited", has_vehicle=True))
    without = evac_time_needed(facts(mobility="limited", has_vehicle=False))
    assert without - with_car == NO_VEHICLE_PENALTY
