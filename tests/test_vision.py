"""Photo intake: type sniffing, EXIF, geo resolution, and evacuation plans."""
import io

import pytest
from PIL import Image

from app import evac_plan, hazards, state, vision
from app.extraction import ExtractedFacts
from app.seeds import MAX_INCIDENT_KM, nearest_street, street_latlng


@pytest.fixture(autouse=True)
def clean():
    state.clear_hazards()
    yield
    state.clear_hazards()


def _img(color, size=(64, 64), fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


# --- upload validation -------------------------------------------------------
def test_sniff_accepts_jpeg_and_png():
    assert vision.sniff_type(_img((10, 10, 10))) == "jpeg"
    assert vision.sniff_type(_img((10, 10, 10), fmt="PNG")) == "png"


def test_sniff_rejects_non_image():
    assert vision.sniff_type(b"#!/bin/sh\nrm -rf /") is None
    assert vision.sniff_type(b"%PDF-1.4") is None


def test_exif_absent_is_graceful():
    loc = vision.locate(_img((20, 20, 20)))
    assert loc["street"] is None
    assert loc["source"] == "no_exif"


def test_corrupt_bytes_never_raise():
    assert vision.read_exif(b"\xff\xd8\xffgarbage")["has_gps"] is False
    facts = vision.analyze(b"\xff\xd8\xffgarbage")
    assert facts.analysis_source in ("offline_heuristic", "none")


# --- geo resolution ----------------------------------------------------------
def test_street_coordinates_round_trip():
    lat, lng = street_latlng("miner's bend")
    name, km = nearest_street(lat, lng)
    assert name == "miner's bend"
    assert km < 0.01


def test_gps_far_away_is_off_map():
    name, km = nearest_street(48.8584, 2.2945)      # Eiffel Tower
    assert name is None
    assert km > MAX_INCIDENT_KM


def test_neighbouring_gps_snaps_to_nearest_street():
    lat, lng = street_latlng("granite pass")
    name, _ = nearest_street(lat + 0.0003, lng + 0.0003)
    assert name == "granite pass"


# --- offline heuristic is a real measurement, not a canned answer ------------
def test_fire_glow_image_reads_as_flames():
    facts = vision.analyze(_img((235, 90, 25)))     # saturated orange frame
    assert facts.analysis_source == "offline_heuristic"
    assert facts.visible_flames is True
    assert "fire-glow" in facts.description


def test_grey_haze_reads_as_smoke_not_flames():
    facts = vision.analyze(_img((150, 148, 145)))   # desaturated grey
    assert facts.visible_flames is False
    assert facts.heavy_smoke is True


def test_clear_blue_sky_reads_as_neither():
    facts = vision.analyze(_img((40, 90, 200)))
    assert facts.visible_flames is False
    assert facts.heavy_smoke is False


# --- evacuation plan is deterministic ---------------------------------------
def test_trapped_plan_says_stay_put():
    facts = ExtractedFacts(physically_trapped=True, location_text="Miner's Bend")
    plan = evac_plan.build(facts, "fire_rescue", {"time_to_impact": -20})
    assert "Stay where you are" in plan["headline"]
    assert any("Do not attempt to drive" in s for s in plan["steps"])


def test_transport_plan_warns_against_self_evacuating():
    facts = ExtractedFacts(mobility="non_ambulatory", location_text="41 Cedar Canyon Rd")
    plan = evac_plan.build(facts, "transport_assist",
                           {"fire_eta": 18, "evac_need": 45, "time_to_impact": -27})
    assert "Transport is dispatched" in plan["headline"]
    assert any("27 min short" in s for s in plan["steps"])


def test_standard_plan_routes_away_from_the_fire():
    facts = ExtractedFacts(mobility="ambulatory", location_text="Pine Hollow Ct")
    plan = evac_plan.build(facts, "standard", {"time_to_impact": 8})
    route = plan["recommended_route"]
    assert route is not None
    # fire origin is north-east, so guidance must trend south and/or west
    assert "south" in route["bearing"] or "west" in route["bearing"]


def test_plan_lists_confirmed_blocked_roads_and_flags_own_street():
    hazards.report("miner's bend", "road_blocked", "c1")
    hazards.report("miner's bend", "road_blocked", "c2")
    facts = ExtractedFacts(mobility="ambulatory", location_text="Miner's Bend")
    plan = evac_plan.build(facts, "standard", {"time_to_impact": 5})
    assert "miner's bend" in plan["blocked_routes"]
    assert any("your own street is reported impassable" in s.lower() for s in plan["steps"])
    assert plan["recommended_route"]["street"] != "miner's bend"


def test_plan_never_routes_through_a_blocked_street():
    for s in ("ridgeway loop", "sumac trail", "granite pass"):
        hazards.report(s, "road_blocked", "a")
        hazards.report(s, "road_blocked", "b")
    blocked = set(hazards.blocked_streets())
    route = evac_plan.safest_route("pine hollow ct", blocked)
    assert route is None or route["street"] not in blocked


def test_plan_is_declared_deterministic():
    plan = evac_plan.build(ExtractedFacts(), "standard", None)
    assert "deterministic" in plan["basis"]
