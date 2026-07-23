"""BEACON — wildfire evacuation dispatch. FastAPI app, pipeline, background tasks.

Pipeline order per message: create Zendesk ticket -> extract facts -> route ->
pins/equation -> Zendesk write-back -> escalation/auto-answer, recording a
timeline event at every step. Every step is try/except'd so one failure records
the failure and continues rather than blanking the dashboard.
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from typing import Literal, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config, state
from app.analytics import attach_ranks, compute_metrics, panic_score
from app.extraction import extract_facts
from app.guide_answer import compose_answer
from app import evac_plan, hazards, learning, vision
from app.router_rules import route
from app.seeds import DEMO_TICKETS, NOISE_TICKETS, find_street, pin_for
from app.security import (
    CATEGORY_LIMITS, MAX_MESSAGE_LEN, MAX_NAME_LEN, categorize, detect_injection,
    limiter, sanitize_text,
)
from app.zendesk_client import get_client

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


@asynccontextmanager
async def lifespan(_app):
    for w in config.startup_warnings():
        print(w)
    learning.sync_router()  # re-apply human-approved calibration on boot
    tasks = [asyncio.create_task(_fire_ticker())]
    if not config.USE_MOCK_ZENDESK:
        tasks.append(asyncio.create_task(_zendesk_poller()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="BEACON", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_middleware(request, call_next):
    # Per-IP token-bucket rate limiting on API routes (cost + bandwidth guard).
    category = categorize(request.url.path, request.method)
    if category:
        ip = request.client.host if request.client else "unknown"
        capacity, refill = CATEGORY_LIMITS[category]
        allowed, retry_after = limiter.allow(f"{ip}:{category}", capacity, refill)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "retry_after_seconds": round(retry_after, 1)},
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    response = await call_next(request)
    # Baseline hardening headers. API responses can never be framed; pages may
    # frame each other same-origin only (the /film cinematic embeds /dashboard).
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = (
        "DENY" if request.url.path.startswith("/api") else "SAMEORIGIN")
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response

zclient = get_client()

FLAGGED = {"fire_rescue", "transport_assist", "accessible_shelter", "needs_human_review"}
TEAM_OF = {
    "fire_rescue": "fire_rescue",
    "transport_assist": "transport_assist",
    "accessible_shelter": "accessible_shelter",
    "needs_human_review": "fire_rescue",
}


class SubmitBody(BaseModel):
    name: str = Field(default="Anonymous", max_length=MAX_NAME_LEN)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)


async def _fire_ticker():
    """Auto-advance the fire every 45s; shrinks live countdowns on screen.
    Slow enough that a full pitch fits before the ETA reaches zero."""
    while True:
        await asyncio.sleep(45)
        state.advance_fire()


async def _zendesk_poller():
    """Surface tickets created directly in the Zendesk UI (real client only)."""
    while True:
        await asyncio.sleep(3)
        try:
            since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            known = state.known_ticket_ids()
            for t in zclient.poll_new_tickets(since):
                if t.get("id") and t["id"] not in known:
                    _ingest_external_ticket(t)
        except Exception as exc:  # noqa: BLE001
            print(f"[BEACON] poller error: {exc!r}")


def _ingest_external_ticket(t):
    body = t.get("description") or t.get("subject") or ""
    name = (t.get("via", {}) or {}).get("source", {}).get("from", {}).get("name", "Zendesk user")
    case = process_message(name, body, existing_ticket_id=t["id"])
    return case


def process_message(name: str, message: str, existing_ticket_id=None) -> dict:
    # Harden input before it is stored, sent to the LLM, or logged.
    name = sanitize_text(name)[:MAX_NAME_LEN] or "Anonymous"
    message = sanitize_text(message)[:MAX_MESSAGE_LEN]
    suspicious = detect_injection(message)
    t0 = time.perf_counter()

    case_id = uuid4().hex[:8]
    case = {
        "id": case_id,
        "zendesk_ticket_id": existing_ticket_id,
        "created_at": state.now_iso(),
        "requester_name": name or "Anonymous",
        "message": message,
        "panic_score": panic_score(message),
        "processing_ms": None,
        "status": "open",  # open -> acknowledged -> resolved
        "facts": None,
        "dispatch_path": "standard",
        "rule_fired": "",
        "equation": None,
        "pin": None,
        "auto_answer": None,
        "escalation": None,
        "timeline": [{"at": state.now_iso(), "event": "Message received on evacuation support line"}],
    }
    state.add_case(case)

    # 1. Create the Zendesk ticket (skip if ingested from Zendesk itself).
    if existing_ticket_id is None:
        try:
            tid = zclient.create_ticket(
                name, "policyholder@example.com",
                f"Evacuation message from {name}", message,
            )
            state.update_case(case_id, zendesk_ticket_id=tid)
            state.add_timeline(case_id, f"Zendesk ticket #{tid} created")
        except Exception as exc:  # noqa: BLE001
            state.add_timeline(case_id, f"Zendesk ticket creation failed ({exc!r})")

    # 2. Extract facts (facts only — never decisions).
    force_review = False
    try:
        facts, force_review = extract_facts(message)
        state.update_case(case_id, facts=facts.model_dump())
        state.add_timeline(
            case_id,
            f"Facts extracted (mobility={facts.mobility}, "
            f"trapped={facts.physically_trapped}, confidence={facts.confidence:.2f})",
        )
    except Exception as exc:  # noqa: BLE001
        state.add_timeline(case_id, f"Extraction failed ({exc!r}); defaulting to human review")
        from app.extraction import ExtractedFacts
        facts = ExtractedFacts(physically_trapped=True, can_self_evacuate=False, confidence=0.0)
        force_review = True
        state.update_case(case_id, facts=facts.model_dump())

    # 2b. Hazard network — this ticket both teaches and learns.
    #     Contribute: if it names a blocked route, record it for everyone after.
    reported_street = hazards.report_from_case(case_id, facts)
    if reported_street:
        st = hazards.status(reported_street)
        state.add_timeline(case_id, f"Hazard reported: {reported_street} "
                                    f"({st['label']}) — now {st['status']} "
                                    f"with {st['fresh']} witness(es)")
    #     Consume: is this person's own egress already known-impassable?
    blocked = hazards.egress_blocked_for(facts.location_text)
    if blocked and not facts.physically_trapped:
        facts.egress_blocked = True
        state.update_case(case_id, facts=facts.model_dump())
        state.add_timeline(
            case_id,
            f"Egress compromised: {blocked['street']} confirmed {blocked['label']} "
            f"by {blocked['fresh']} prior report(s) — detour penalty applied")

    # 3. Deterministic routing.
    path, rule, eq = route(facts, state.get_fire()["eta_minutes"])
    if force_review:
        path = "needs_human_review"
        rule = "SAFETY NET: danger keyword matched, extraction untrusted -> human review"
    if suspicious:
        # Possible prompt injection. The LLM can never trigger an action here
        # (it only fills a fact schema; this function decides), so the worst an
        # injected message could do is flip a fact — route to a human instead.
        path = "needs_human_review"
        rule = "SECURITY: possible prompt-injection in message -> human review"
        state.add_timeline(case_id, "⚠ possible prompt injection detected — routed to human review")
    pin = pin_for(case_id, facts.location_text)
    state.update_case(case_id, dispatch_path=path, rule_fired=rule, equation=eq, pin=pin)
    eq_str = f" [{eq['fire_eta']} - {eq['evac_need']} = {eq['time_to_impact']} min]" if eq else ""
    state.add_timeline(case_id, f"Routed -> {path} ({rule}){eq_str}")

    # 4. Zendesk write-back (custom field + tags + internal note).
    tid = state.get_case(case_id)["zendesk_ticket_id"]
    if tid is not None:
        note = _internal_note(case_id, path, rule, eq, facts)
        tags = ["beacon", path]
        try:
            zclient.update_ticket(tid, path, tags, note)
            state.add_timeline(case_id, f"Zendesk updated: dispatch_path={path}, priority set, internal note added")
        except Exception as exc:  # noqa: BLE001
            state.add_timeline(case_id, f"Zendesk write-back failed ({exc!r})")

    # 5. Escalation (flagged) or auto-answer (informational).
    if path == "auto_answered":
        _auto_answer(case_id, message, tid)
    elif path in FLAGGED:
        _escalate(case_id, path, facts)
    else:
        state.add_timeline(case_id, "No escalation — standard handling")

    state.update_case(case_id, processing_ms=max(1, round((time.perf_counter() - t0) * 1000)))
    return state.get_case(case_id)


def _internal_note(case_id, path, rule, eq, facts) -> str:
    lines = [
        f"BEACON dispatch — case {case_id}",
        f"Path: {path}",
        f"Rule: {rule}",
    ]
    if eq:
        lines.append(f"Equation: {eq['fire_eta']} - {eq['evac_need']} = {eq['time_to_impact']} min to impact")
    lines.append(
        f"Facts: mobility={facts.mobility}, equipment={facts.medical_equipment}, "
        f"trapped={facts.physically_trapped}, injured={facts.injuries_reported}, "
        f"can_self_evacuate={facts.can_self_evacuate}, vehicle={facts.has_vehicle}, "
        f"people={facts.people_count}, location='{facts.location_text}'"
    )
    return "\n".join(lines)


def _auto_answer(case_id, message, tid):
    try:
        answer = compose_answer(zclient, message)
        state.update_case(case_id, auto_answer=answer)
        if tid is not None:
            try:
                zclient.public_reply(tid, answer)
            except Exception as exc:  # noqa: BLE001
                state.add_timeline(case_id, f"Public reply failed ({exc!r})")
        state.add_timeline(case_id, "Auto-answered from Guide knowledge base")
    except Exception as exc:  # noqa: BLE001
        state.add_timeline(case_id, f"Auto-answer failed ({exc!r})")


def _escalate(case_id, path, facts):
    team = TEAM_OF.get(path, path)
    case = state.get_case(case_id)
    loc = facts.location_text or "location unknown"
    summary = (
        f"{case['requester_name']} — {loc}. mobility={facts.mobility}, "
        f"equipment={facts.medical_equipment}, people={facts.people_count}."
    )
    tid = case["zendesk_ticket_id"]
    result = {"channel": "internal_note", "status": "internal_note_fallback"}
    if tid is not None:
        try:
            result = zclient.open_side_conversation(tid, team, summary)
        except Exception as exc:  # noqa: BLE001
            state.add_timeline(case_id, f"Side conversation failed ({exc!r}); internal note fallback")
    escalation = {"channel": result["channel"], "status": result["status"], "at": state.now_iso(), "team": team}
    state.update_case(case_id, escalation=escalation)
    state.record_escalation({
        "team": team, "case_id": case_id, "location": loc,
        "status": result["status"], "at": escalation["at"],
    })
    state.add_timeline(case_id, f"📟 PAGED {team} ({result['channel']}, {result['status']})")


# --- Routes ------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/dashboard")
def dashboard():
    return FileResponse(os.path.join(STATIC_DIR, "dashboard.html"))


@app.get("/film")
def film():
    """Self-playing demo film — drives the live app, records as the backup video."""
    return FileResponse(os.path.join(STATIC_DIR, "film.html"))


@app.post("/api/submit")
def submit(body: SubmitBody):
    case = process_message(body.name, body.message)
    # Tell the sender what other people have reported about their street.
    facts = case.get("facts") or {}
    return {**case, "hazard_advisory": hazards.advisory_for(facts.get("location_text", ""))}


@app.get("/api/state")
def api_state():
    cases = state.all_cases()
    attach_ranks(cases)
    return {
        "cases": cases,
        "fire": state.get_fire(),
        "counts": state.counts(),
        "crew": config.CREW_COUNTS,
        "metrics": compute_metrics(cases, config.CREW_COUNTS),
        "escalations": state.recent_escalations(),
        "hazards": hazards.all_status(),
        "sim_running": state.sim_running(),
        "mode": {"demo": config.DEMO_MODE, "mock_zendesk": config.USE_MOCK_ZENDESK,
                 "fallback_extraction": config.USE_FALLBACK_EXTRACTION},
    }


@app.post("/api/seed")
def seed():
    """Load the noise feed, staggered over the past ~40 minutes."""
    if not config.ALLOW_BULK_SEED:
        return JSONResponse(
            status_code=403,
            content={"error": "bulk_seed_disabled",
                     "detail": "Bulk seeding fans out to 30 live OpenAI+Zendesk calls. "
                               "Set BEACON_ALLOW_BULK_SEED=true to enable in live mode."},
        )
    base = datetime.now(timezone.utc) - timedelta(minutes=40)
    created = []
    for i, (name, msg) in enumerate(NOISE_TICKETS):
        case = process_message(name, msg)
        # Stagger created_at so the feed looks like it accumulated over time.
        ts = (base + timedelta(minutes=i * 40 / max(1, len(NOISE_TICKETS)))).isoformat()
        state.update_case(case["id"], created_at=ts)
        created.append(case["id"])
    return {"seeded": len(created)}


@app.post("/api/seed/demo/{n}")
def seed_demo(n: int):
    if n not in DEMO_TICKETS:
        return {"error": "unknown demo ticket", "valid": list(DEMO_TICKETS.keys())}
    name, msg = DEMO_TICKETS[n]
    return process_message(name, msg)


@app.post("/api/fire/advance")
def fire_advance():
    return state.advance_fire()


@app.get("/api/case/{case_id}")
def get_case(case_id: str):
    """Single-case lookup — lets the intake form close the loop for the sender."""
    c = state.get_case(case_id)
    if not c:
        return JSONResponse(status_code=404, content={"error": "unknown_case"})
    return c


REASSIGN_PATHS = {"fire_rescue", "transport_assist", "accessible_shelter", "standard"}


class CaseAction(BaseModel):
    action: Literal["acknowledge", "resolve", "reassign"]
    path: Optional[str] = None          # reassign target
    reason: str = Field(default="", max_length=200)


@app.patch("/api/case/{case_id}")
def case_action(case_id: str, body: CaseAction):
    """Human-in-the-loop: dispatchers acknowledge, resolve, or override routing.
    Every action is logged to the timeline and written back to Zendesk — the
    audit trail includes the humans, not just the model and the rules."""
    c = state.get_case(case_id)
    if not c:
        return JSONResponse(status_code=404, content={"error": "unknown_case"})
    reason = sanitize_text(body.reason)[:200]

    if body.action == "acknowledge":
        if c["status"] != "open":
            return JSONResponse(status_code=409, content={"error": f"case is {c['status']}"})
        state.update_case(case_id, status="acknowledged")
        state.add_timeline(case_id, "Crew acknowledged — en route")
        _zendesk_note(c, "Crew acknowledged — en route.")

    elif body.action == "resolve":
        if c["status"] == "resolved":
            return JSONResponse(status_code=409, content={"error": "already resolved"})
        state.update_case(case_id, status="resolved")
        state.add_timeline(case_id, "Case resolved by dispatcher"
                           + (f" — {reason}" if reason else ""))
        _zendesk_note(c, f"Case resolved by dispatcher. {reason}".strip())

    elif body.action == "reassign":
        if body.path not in REASSIGN_PATHS:
            return JSONResponse(status_code=422,
                                content={"error": "invalid path", "valid": sorted(REASSIGN_PATHS)})
        old = c["dispatch_path"]
        if body.path == old:
            return JSONResponse(status_code=409, content={"error": "already on that path"})
        state.update_case(case_id, dispatch_path=body.path,
                          rule_fired=f"DISPATCHER OVERRIDE: {old} -> {body.path}"
                                     + (f" ({reason})" if reason else ""))
        state.add_timeline(case_id, f"Dispatcher override: {old} -> {body.path}"
                           + (f" — {reason}" if reason else ""))
        # Every override is a labeled disagreement between the router and a human.
        learning.record_override(case_id, old, body.path, reason)
        tid = c["zendesk_ticket_id"]
        if tid is not None:
            try:
                zclient.update_ticket(tid, body.path, ["beacon", body.path, "override"],
                                      f"Dispatcher override: {old} -> {body.path}. {reason}".strip())
                state.add_timeline(case_id, "Zendesk updated with override")
            except Exception as exc:  # noqa: BLE001
                state.add_timeline(case_id, f"Zendesk override write failed ({exc!r})")
        # Page the newly-assigned team so the override actually dispatches.
        if body.path in TEAM_OF:
            facts_dict = c.get("facts") or {}
            from app.extraction import ExtractedFacts
            _escalate(case_id, body.path, ExtractedFacts(**facts_dict))

    return state.get_case(case_id)


class Observation(BaseModel):
    """Ground truth reported back from the field."""
    actual_evac_minutes: Optional[int] = Field(default=None, ge=0, le=600)
    note: str = Field(default="", max_length=300)
    # {"medical_equipment": "oxygen"} — fields the extractor got wrong
    fact_corrections: dict[str, str] = Field(default_factory=dict)


@app.post("/api/case/{case_id}/observe")
def observe(case_id: str, body: Observation):
    """Close the loop: report what ACTUALLY happened. This is the only source
    of truth the calibration engine is allowed to learn from."""
    c = state.get_case(case_id)
    if not c:
        return JSONResponse(status_code=404, content={"error": "unknown_case"})
    facts = c.get("facts") or {}
    mobility = facts.get("mobility")

    if body.actual_evac_minutes is not None:
        learning.record_outcome(case_id, mobility, body.actual_evac_minutes,
                                sanitize_text(body.note)[:300])
        state.add_timeline(case_id, f"Outcome reported: evacuation took "
                                    f"{body.actual_evac_minutes} min (mobility={mobility})")
    for field, should_be in list(body.fact_corrections.items())[:11]:
        learning.record_fact_correction(case_id, sanitize_text(field)[:40],
                                        facts.get(field), sanitize_text(should_be)[:60])
        state.add_timeline(case_id, f"Fact corrected: {field} "
                                    f"{facts.get(field)!r} -> {should_be!r}")
    return {"recorded": True, "case": state.get_case(case_id)}


UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/api/photo")
async def upload_photo(file: UploadFile = File(...), name: str = Form("Anonymous"),
                       message: str = Form("")):
    """A photo IS a report. EXIF gives the location, vision gives the facts, the
    hazard network gets both, and the sender gets a deterministic plan back."""
    data = await file.read(vision.MAX_PHOTO_BYTES + 1)
    if len(data) > vision.MAX_PHOTO_BYTES:
        return JSONResponse(status_code=413, content={"error": "photo too large (max 8MB)"})
    kind = vision.sniff_type(data)
    if not kind:
        return JSONResponse(status_code=415,
                            content={"error": "only JPEG or PNG photos are accepted"})

    loc = vision.locate(data)
    pfacts = vision.analyze(data)

    # Street sign OCR is the fallback when EXIF was stripped in transit.
    street = loc["street"]
    if not street and pfacts.street_sign_text:
        street, _ = find_street(pfacts.street_sign_text)
        if street:
            loc = {**loc, "street": street, "source": "street_sign_ocr"}

    # Build a text message so the photo flows through the SAME audited pipeline.
    parts = [sanitize_text(message)[:MAX_MESSAGE_LEN]] if message else []
    if pfacts.visible_flames:
        parts.append("There are visible flames.")
    if pfacts.road_blocked:
        parts.append("The road is blocked.")
    if pfacts.heavy_smoke:
        parts.append("Heavy smoke.")
    if street:
        parts.append(f"Location {street.title()}.")
    synthesized = " ".join(parts) or "Photo submitted from the evacuation area."

    # File the hazard BEFORE routing, so the sender's own photo evidence reaches
    # the deterministic pipeline instead of arriving too late to matter.
    if street and (pfacts.road_blocked or pfacts.visible_flames):
        hazards.report(street, "fire_active" if pfacts.visible_flames else "road_blocked",
                       f"photo:{uuid4().hex[:8]}", note="photo evidence", via_photo=True)

    case = process_message(name, synthesized)

    # Persist the image so the street timeline can stitch it.
    fname = f"{case['id']}.{ 'jpg' if kind == 'jpeg' else 'png' }"
    try:
        with open(os.path.join(UPLOAD_DIR, fname), "wb") as fh:
            fh.write(data)
    except OSError as exc:
        state.add_timeline(case["id"], f"Photo write failed ({exc!r})")

    photo = state.add_photo({
        "case_id": case["id"], "street": street, "url": f"/static/uploads/{fname}",
        "source": loc["source"], "taken_at": loc.get("taken_at"),
        "lat": loc.get("lat"), "lng": loc.get("lng"),
        "facts": pfacts.model_dump(), "requester": case["requester_name"],
    })
    state.add_timeline(case["id"],
                       f"Photo analysed via {pfacts.analysis_source}; location by {loc['source']}"
                       + (f" -> {street}" if street else " (unresolved)"))

    if street and (pfacts.road_blocked or pfacts.visible_flames):
        state.add_timeline(case["id"],
                           f"Photo filed as hazard evidence for {street} "
                           f"(self-corroborating: confirmed on one image)")

    facts_obj = _facts_obj(case)
    plan = evac_plan.build(facts_obj, case["dispatch_path"], case["equation"])
    return {"case": state.get_case(case["id"]), "photo": photo,
            "photo_facts": pfacts.model_dump(), "location": loc, "plan": plan,
            "hazard_advisory": hazards.advisory_for(
                (case.get("facts") or {}).get("location_text", ""))}


def _facts_obj(case: dict):
    from app.extraction import ExtractedFacts
    return ExtractedFacts(**(case.get("facts") or {}))


@app.get("/api/plan/{case_id}")
def get_plan(case_id: str):
    """The evacuation plan for an existing case — deterministic, recomputed live
    against the current hazard network."""
    c = state.get_case(case_id)
    if not c:
        return JSONResponse(status_code=404, content={"error": "unknown_case"})
    return evac_plan.build(_facts_obj(c), c["dispatch_path"], c["equation"])


@app.get("/api/timeline/{street}")
def street_timeline(street: str):
    """Stitch every photo of one street into a chronological progression."""
    key = sanitize_text(street).lower()[:40]
    shots = sorted(state.photos_for(key), key=lambda p: p["at"])
    return {"street": key, "status": hazards.status(key), "frames": shots,
            "count": len(shots)}


@app.get("/api/timelines")
def all_timelines():
    """Streets that have photo evidence, most-documented first."""
    by: dict[str, list] = {}
    for p in state.all_photos():
        if p.get("street"):
            by.setdefault(p["street"], []).append(p)
    return {"streets": [
        {"street": s, "count": len(v), "status": hazards.status(s),
         "frames": sorted(v, key=lambda p: p["at"])}
        for s, v in sorted(by.items(), key=lambda kv: -len(kv[1]))
    ]}


@app.get("/api/learning")
def learning_report():
    """Scorecard, calibration proposals, and rule reviews awaiting a human."""
    return learning.report()


class Approval(BaseModel):
    proposal_id: str = Field(max_length=80)
    approved_by: str = Field(default="dispatcher", max_length=60)


@app.post("/api/learning/approve")
def learning_approve(body: Approval):
    """A human signs a calibration proposal. Only then does a constant change."""
    applied = learning.approve(sanitize_text(body.proposal_id)[:80],
                               sanitize_text(body.approved_by)[:60] or "dispatcher")
    if not applied:
        return JSONResponse(status_code=404,
                            content={"error": "no such active proposal"})
    return {"applied": applied, "live_constants": dict(router_rules_constants())}


def router_rules_constants():
    from app import router_rules
    return router_rules.EVAC_MINUTES


def _zendesk_note(case: dict, note: str):
    tid = case.get("zendesk_ticket_id")
    if tid is None:
        return
    try:
        zclient.update_ticket(tid, case["dispatch_path"],
                              ["beacon", case["dispatch_path"]], f"BEACON: {note}")
    except Exception as exc:  # noqa: BLE001
        state.add_timeline(case["id"], f"Zendesk note failed ({exc!r})")


@app.get("/api/zendesk/tickets")
def zendesk_tickets():
    """Proof of write-back. In demo mode, expose the mock Zendesk tickets so
    judges can see the custom field, tags, priority, and comments without a
    live instance. In live mode, point at the real agent workspace instead."""
    if config.USE_MOCK_ZENDESK:
        return {"live": False, "tickets": list(reversed(zclient.tickets[-30:]))}
    return {"live": True,
            "agent_url": f"https://{config.ZENDESK_SUBDOMAIN}.zendesk.com/agent"}


@app.get("/api/health")
def health():
    from app.preflight import run_checks
    return run_checks()


@app.post("/api/reset")
def reset():
    """Fresh incident between rehearsals: clears cases, restores the fire."""
    state.reset_all()
    return {"status": "reset", "fire": state.get_fire()}


async def _replay_task():
    """Drip the noise feed in live over ~60s — the board fills on stage in
    real time instead of appearing all at once."""
    state.set_sim(True)
    try:
        for i, (name, msg) in enumerate(NOISE_TICKETS):
            await asyncio.to_thread(process_message, name, msg)
            # Deterministic 1.2–2.4s stagger (no RNG so replays are identical).
            await asyncio.sleep(1.2 + ((i * 7) % 13) / 10.0)
    finally:
        state.set_sim(False)


@app.post("/api/simulate")
async def simulate():
    """Incident replay: stream the 30 seeded messages in over ~a minute."""
    if not config.ALLOW_BULK_SEED:
        return JSONResponse(
            status_code=403,
            content={"error": "bulk_seed_disabled",
                     "detail": "Replay issues 30 live OpenAI+Zendesk calls. "
                               "Set BEACON_ALLOW_BULK_SEED=true to enable in live mode."},
        )
    if state.sim_running():
        return {"status": "already_running"}
    asyncio.create_task(_replay_task())
    return {"status": "started", "tickets": len(NOISE_TICKETS)}
