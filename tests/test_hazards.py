"""Hazard network — corroboration, staleness, and effect on dispatch."""
import pytest

from app import hazards, state
from app.extraction import ExtractedFacts
from app.router_rules import evac_time_needed, route


@pytest.fixture(autouse=True)
def clean():
    state.clear_hazards()
    yield
    state.clear_hazards()


# --- corroboration ladder ----------------------------------------------------
def test_unknown_street_is_ignored():
    assert hazards.report("nowhere blvd", "road_blocked", "c1") is None
    assert hazards.all_status() == []


def test_single_report_is_advisory_not_impassable():
    hazards.report("miner's bend", "road_blocked", "c1")
    st = hazards.status("miner's bend")
    assert st["status"] == "reported"
    assert st["impassable"] is False
    assert st["fresh"] == 1


def test_two_independent_reports_confirm():
    hazards.report("miner's bend", "road_blocked", "c1")
    hazards.report("miner's bend", "road_blocked", "c2")
    st = hazards.status("miner's bend")
    assert st["status"] == "confirmed"
    assert st["impassable"] is True
    assert st["case_ids"] == ["c1", "c2"]


def test_one_person_filing_repeatedly_is_one_witness():
    """A panicking person filing five tickets must not self-confirm a hazard."""
    for _ in range(5):
        hazards.report("miner's bend", "road_blocked", "same_case")
    st = hazards.status("miner's bend")
    assert st["fresh"] == 1
    assert st["impassable"] is False
    assert st["total"] == 5


def test_clear_street_reports_clear():
    st = hazards.status("granite pass")
    assert st["status"] == "clear"
    assert st["impassable"] is False


def test_active_fire_outranks_plain_block():
    hazards.report("miner's bend", "road_blocked", "c1")
    hazards.report("miner's bend", "fire_active", "c2")
    assert hazards.status("miner's bend")["kind"] == "fire_active"


def test_stale_reports_age_out():
    hazards.report("miner's bend", "road_blocked", "c1")
    hazards.report("miner's bend", "road_blocked", "c2")
    # backdate every report beyond the staleness window
    for h in state._hazards.values():          # noqa: SLF001 (test introspection)
        for r in h["reports"]:
            r["at"] = "2020-01-01T00:00:00+00:00"
    st = hazards.status("miner's bend")
    assert st["status"] == "stale"
    assert st["impassable"] is False


# --- effect on dispatch ------------------------------------------------------
def test_blocked_egress_adds_named_penalty():
    clear = ExtractedFacts(mobility="ambulatory", has_vehicle=True)
    blocked = ExtractedFacts(mobility="ambulatory", has_vehicle=True, egress_blocked=True)
    assert evac_time_needed(blocked) - evac_time_needed(clear) == 25


def test_someone_who_thinks_they_can_drive_out_gets_reclassified():
    """The headline case: ambulatory + vehicle normally clears easily. With a
    confirmed impassable egress, the math flips them into transport assist."""
    fine = ExtractedFacts(mobility="ambulatory", has_vehicle=True, location_text="Miner's Bend")
    path, _, eq = route(fine, 18)
    assert path == "standard" and eq["time_to_impact"] == 8

    blocked = fine.model_copy(update={"egress_blocked": True})
    path2, rule2, eq2 = route(blocked, 18)
    assert eq2["evac_need"] == 35
    assert eq2["time_to_impact"] == -17
    assert path2 == "transport_assist"
    assert "R2" in rule2


def test_egress_lookup_only_fires_when_confirmed():
    assert hazards.egress_blocked_for("41 Miner's Bend") is None
    hazards.report("miner's bend", "road_blocked", "c1")
    assert hazards.egress_blocked_for("41 Miner's Bend") is None   # 1 witness
    hazards.report("miner's bend", "road_blocked", "c2")
    assert hazards.egress_blocked_for("41 Miner's Bend")["impassable"] is True


def test_advisory_fires_even_when_unconfirmed():
    hazards.report("miner's bend", "road_blocked", "c1")
    adv = hazards.advisory_for("Miner's Bend")
    assert adv["status"] == "reported"


def test_report_from_case_derives_street_and_kind():
    facts = ExtractedFacts(road_blocked=True, physically_trapped=True,
                           location_text="Miner's Bend")
    assert hazards.report_from_case("c1", facts) == "miner's bend"
    assert hazards.status("miner's bend")["kind"] == "fire_active"


def test_report_from_case_noop_without_road_block():
    facts = ExtractedFacts(location_text="Miner's Bend")
    assert hazards.report_from_case("c1", facts) is None
    assert hazards.all_status() == []


def test_blocked_streets_listing():
    hazards.report("miner's bend", "road_blocked", "c1")
    hazards.report("miner's bend", "road_blocked", "c2")
    hazards.report("granite pass", "road_blocked", "c3")
    assert hazards.blocked_streets() == ["miner's bend"]
