import os

os.environ.setdefault("DEMO_MODE", "true")

from app.analytics import attach_ranks, compute_metrics, panic_score

CREW = {"fire_rescue": 2, "transport_assist": 3, "accessible_shelter": 99}


def test_panicked_faq_scores_higher_than_calm_emergency():
    faq = panic_score("IS MY DEDUCTIBLE WAIVED?? I NEED AN ANSWER NOW!!!")
    calm = panic_score("My son and I both use wheelchairs. We're at 41 Cedar Canyon Rd.")
    assert faq > 50 and calm < 20 and faq > calm


def test_panic_score_bounds():
    assert panic_score("") == 0
    assert panic_score("HELP!!! NOW!!! URGENT!!! " * 40) == 100


def case(id_, path, panic, tti, status="open"):
    return {
        "id": id_, "dispatch_path": path, "panic_score": panic,
        "created_at": f"2026-07-23T00:00:0{id_}", "status": status,
        "equation": {"fire_eta": 18, "evac_need": 18 - tti, "time_to_impact": tti}
        if tti is not None else None,
        "processing_ms": 2,
    }


def test_rank_inversion_loud_faq_vs_calm_rescue():
    cases = [
        case("1", "auto_answered", 90, None),
        case("2", "fire_rescue", 5, -27),
    ]
    attach_ranks(cases)
    by_id = {c["id"]: c for c in cases}
    assert by_id["1"]["tone_rank"] == 1 and by_id["1"]["need_rank"] == 2
    assert by_id["2"]["tone_rank"] == 2 and by_id["2"]["need_rank"] == 1


def test_need_rank_orders_by_least_margin():
    cases = [
        case("1", "transport_assist", 0, 5),
        case("2", "transport_assist", 0, -30),
    ]
    attach_ranks(cases)
    assert next(c for c in cases if c["id"] == "2")["need_rank"] == 1


def test_metrics_deflection_and_lanes():
    cases = [
        case("1", "auto_answered", 50, None),
        case("2", "auto_answered", 50, None),
        case("3", "fire_rescue", 5, -27),
        case("4", "needs_human_review", 5, -27),
    ]
    m = compute_metrics(cases, CREW)
    assert m["total"] == 4 and m["deflected_pct"] == 50
    # human-review cases count against the rescue crew
    assert m["lanes"]["fire_rescue"]["active"] == 2
    assert m["lanes"]["fire_rescue"]["saturated"] is False


def test_resolved_cases_free_the_crew():
    cases = [
        case("1", "fire_rescue", 5, -27),
        case("2", "fire_rescue", 5, -27, status="resolved"),
        case("3", "fire_rescue", 5, -27),
        case("4", "fire_rescue", 5, -27),
    ]
    m = compute_metrics(cases, CREW)
    assert m["lanes"]["fire_rescue"]["active"] == 3
    assert m["lanes"]["fire_rescue"]["saturated"] is True  # 3 > capacity 2
