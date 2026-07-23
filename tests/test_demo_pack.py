"""The bundled demo photo pack must be stage-ready — verified, not assumed."""
import os

import pytest
from fastapi.testclient import TestClient

from app import state, vision
from app.main import DEMO_DIR, DEMO_PHOTOS, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    state.reset_all()
    yield
    state.reset_all()


def test_every_demo_photo_exists():
    for n, (fname, _, _) in DEMO_PHOTOS.items():
        assert os.path.isfile(os.path.join(DEMO_DIR, fname)), f"demo photo {n} missing"


def test_every_demo_photo_carries_resolvable_gps():
    """A venue photo resolves off-map; the pack must resolve inside the town."""
    for n, (fname, _, _) in DEMO_PHOTOS.items():
        data = open(os.path.join(DEMO_DIR, fname), "rb").read()
        loc = vision.locate(data)
        assert loc["source"] == "exif_gps", f"{fname} lost its GPS"
        assert loc["street"] is not None, f"{fname} resolved off-map"
        assert loc["taken_at"], f"{fname} has no capture time"


def test_fire_photos_actually_read_as_fire():
    """Guards against the demo pack silently drifting away from the detector."""
    for fname in ("mb-1.jpg", "mb-2.jpg", "gp-1.jpg"):
        facts = vision.analyze(open(os.path.join(DEMO_DIR, fname), "rb").read())
        assert facts.visible_flames is True, f"{fname} no longer reads as flames"
    smoke = vision.analyze(open(os.path.join(DEMO_DIR, "mb-3.jpg"), "rb").read())
    assert smoke.heavy_smoke is True and smoke.visible_flames is False


def test_seed_photo_endpoint_routes_and_plans():
    r = client.post("/api/seed/photo/1")
    assert r.status_code == 200
    d = r.json()
    assert d["location"]["street"] == "miner's bend"
    assert d["photo_facts"]["visible_flames"] is True
    # geotagged flames alone must escalate — no typing required
    assert d["case"]["dispatch_path"] in ("transport_assist", "fire_rescue")
    assert d["plan"]["headline"]
    assert "deterministic" in d["plan"]["basis"]


def test_unknown_demo_photo_is_404():
    assert client.post("/api/seed/photo/99").status_code == 404


def test_pack_builds_a_street_timeline_in_order():
    for n in (1, 2, 3):
        client.post(f"/api/seed/photo/{n}")
    frames = client.get("/api/timeline/miner's bend").json()["frames"]
    assert len(frames) == 3
    taken = [f["taken_at"] for f in frames]
    assert taken == sorted(taken), "timeline frames out of chronological order"


def test_pack_confirms_two_separate_streets():
    for n in (1, 4):
        client.post(f"/api/seed/photo/{n}")
    streets = {s["street"] for s in client.get("/api/timelines").json()["streets"]}
    assert streets == {"miner's bend", "granite pass"}
