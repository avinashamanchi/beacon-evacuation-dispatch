"""Demo-mode extraction must route the scripted demo beats exactly."""
import os

os.environ.setdefault("DEMO_MODE", "true")

from app.extraction import _safety_net, extract_facts
from app.router_rules import route
from app.seeds import DEMO_TICKETS

FIRE = 18


def route_message(msg):
    facts, force = extract_facts(msg)
    path, rule, eq = route(facts, FIRE)
    if force:
        path = "needs_human_review"
    return path, facts, eq


def test_demo1_panicked_faq_auto_answers():
    path, _, _ = route_message(DEMO_TICKETS[1][1])
    assert path == "auto_answered"


def test_demo2_wheelchairs_transport_minus_27():
    path, facts, eq = route_message(DEMO_TICKETS[2][1])
    assert path == "transport_assist"
    assert facts.mobility == "non_ambulatory"
    assert eq["time_to_impact"] == -27


def test_demo3_trapped_fire_rescue():
    path, facts, _ = route_message(DEMO_TICKETS[3][1])
    assert path == "fire_rescue" and facts.physically_trapped


def test_demo4_spanish_fire_rescue():
    path, facts, _ = route_message(DEMO_TICKETS[4][1])
    assert path == "fire_rescue"
    assert facts.people_count == 2
    assert "miner's bend" in facts.location_text.lower()


def test_neighbor_house_fire_is_not_rescue():
    # "The house next door is on fire" must not trigger R1 for the sender.
    _, facts, _ = route_message(DEMO_TICKETS[2][1])
    assert not facts.physically_trapped


def test_safety_net_danger_forces_review():
    facts, force = _safety_net("we are trapped, flames everywhere")
    assert force and facts.physically_trapped and facts.confidence == 0.0


def test_safety_net_spanish_danger():
    facts, force = _safety_net("estamos atrapados por las llamas")
    assert force and facts.physically_trapped


def test_safety_net_routine_stays_standard():
    facts, force = _safety_net("when can we return home?")
    assert not force and not facts.physically_trapped


def test_oxygen_evacuated_goes_to_shelter():
    path, _, _ = route_message(
        "We already evacuated but my mother is on oxygen, the shelter says no machines")
    assert path == "accessible_shelter"
