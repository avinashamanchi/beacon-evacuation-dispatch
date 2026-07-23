# BEACON — Cedar Canyon Evacuation Dispatch

A wildfire-evacuation support desk. Messages arrive during an evacuation; most
are routine, a few describe people who need physical help. BEACON creates a
Zendesk ticket for each, uses an OpenAI model to **extract facts only**, runs a
**deterministic rules router** to choose a dispatch path, writes the decision
back to Zendesk, and shows everything on a live dispatch dashboard.

> The town, the outage feed, and the customer names are **simulated**. The
> tickets, the extraction, the routing, and the Zendesk write-back are live.

## Core principle

The LLM extracts facts. A plain Python function (`app/router_rules.py`) decides.
Every decision comes with an auditable **Dispatch Receipt**.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # DEMO_MODE=true works with zero network
uvicorn app.main:app --reload --port 8000
```

- Judge intake form: <http://localhost:8000/>
- Dispatch dashboard: <http://localhost:8000/dashboard>

`DEMO_MODE=true` runs with **zero network** — mock Zendesk (in-memory tickets)
and canned keyword extraction. The dashboard and demo flow are identical to a
live run. Missing OpenAI or Zendesk creds auto-fall-back to mock/keyword mode
even when `DEMO_MODE=false`.

## Live mode (.env)

| var | purpose |
|-----|---------|
| `OPENAI_API_KEY` / `OPENAI_MODEL` | structured fact extraction |
| `ZENDESK_SUBDOMAIN` / `ZENDESK_EMAIL` / `ZENDESK_API_TOKEN` | Support + Guide + Side Conversations |
| `ZENDESK_DISPATCH_FIELD_ID` | numeric ID of the `dispatch_path` drop-down field |
| `FIRE_ETA_MINUTES` | starting fire ETA (default 18) |
| `CREW_COUNTS` | JSON crew availability per lane |

## What makes this different

- **TONE ≠ NEED scatter** — every message gets a deterministic `panic_score`
  (exclamations, caps, urgency lexicon). The dashboard plots how *loud* each
  message sounds against how *urgent* it actually is. The FAQ flood clusters
  "LOUD & FINE"; the calm wheelchair user sits alone in "CALM & CRITICAL."
  BEACON routes on the x-axis only.
- **Counterfactual queue rank** — every case shows `tone queue #N → beacon #M`:
  where a tone-sorted queue would have served it vs where BEACON did. The
  panicked deductible question is tone #1 / need #3; the calm trapped caller is
  tone #3 / need #1.
- **Incident replay** (`POST /api/simulate` or press `R`) — streams the 30
  seeded messages in over ~60 s so the board fills live on stage.
- **Ops metrics strip** — total messages, auto-answer deflection %, flagged
  count, median pipeline latency.
- **Crew load bars** — active cases vs crew capacity per lane, `SAT` warning
  when over capacity.
- **Radio log** — newest pipeline event ticks across the footer.
- **Receipt export** — any Dispatch Receipt downloads as JSON (an audit artifact).
- **Keyboard stage controls** — `1`/`2`/`3`/`4` demo tickets, `R` replay, `F`
  advance fire, `M` dispatch ping, `?` cheat sheet, `Esc` close.
- **The loop closes for the sender** — the intake form shows the outcome
  live: the panicked FAQ gets its Guide answer back in under a second; the
  calm emergency gets *"Help is being dispatched to 41 Cedar Canyon Rd —
  routed on what you need, not how it sounds."*
- **Multilingual** — demo `4` is a Spanish emergency ("Estamos atrapados…
  las llamas bloquean la salida") → fire/rescue. The OpenAI extractor is
  language-agnostic; the offline keyword paths carry Spanish stems too.
- **Zendesk write-back proof** — any receipt → "View in Zendesk" shows the
  ticket (priority, `dispatch_path` field, tags, internal note, public reply)
  even in demo mode; in live mode it opens the real agent workspace.
- **Dispatch ping** — optional two-tone Web Audio chirp when a flagged case
  lands (off by default, `M` to toggle).
- **Reset** — one click restores a fresh incident between rehearsals.
- **Case lifecycle + human-in-the-loop** — dispatchers Acknowledge (EN ROUTE
  chip), Resolve (frees the crew, case archives to the feed), or Override the
  routing with a reason. Every action lands in the timeline and Zendesk — the
  audit trail includes the humans, not just the model and the rules.
- **Live case aging** — flagged cards tick mm:ss since arrival; red when the
  evacuation math has gone negative.
- **Test suite** — `pytest` (51 tests, <1s, fully offline): every routing rule,
  extraction beat, security control, and API endpoint including lifecycle
  transitions and rate limits. `pip install -r requirements-dev.txt && pytest`.
- **Venue preflight** — `python -m app.preflight` (or `GET /api/health`)
  verifies creds, Zendesk auth reachability, field IDs, and config before
  you're on stage. Exit 0 = ready to demo.

## The film

`http://localhost:8010/film` — a ~2-minute self-playing demo film. Cold-opens
on the Eaton fire evidence, then **drives the live app** through every beat
(reset → replay → the four demo tickets → fire advance → the scatter → a
camera dolly into a Dispatch Receipt) with timed captions and CSS camera
moves. Every frame is the real product. `Space` pauses, `R` restarts, `N`
toggles a synced narration teleprompter, `V` plays an AI voiceover track
that auto-syncs beat-by-beat (pauses at real silence boundaries, resumes on
each film cue). Full script + recording options in [NARRATION.md](NARRATION.md).
Screen-record it once (`Cmd+Shift+5`) for the backup video and submission
clip — see [VIDEO-PROMPTS.md](VIDEO-PROMPTS.md) for recording steps and
optional AI b-roll prompts.

## 5-step demo checklist

1. Open the dashboard, press **R** (Replay incident) — the noise feed streams
   in live; the scatter fills "LOUD & FINE."
2. Press **1** (deductible panic) → auto-answered from Guide, lands in the gray
   feed at tone #1.
3. Press **2** (wheelchairs at 41 Cedar Canyon Rd) → amber pin, equation
   `18 − 45 = −27 min`, routes to **transport assist**, pager fires.
4. Press **3** (trapped at Miner's Bend) → **fire/rescue**, different pin,
   different pager. Two urgent-sounding messages, two teams.
5. Click any flagged card → **Dispatch Receipt**: facts → rule → equation →
   counterfactual → team paged → timeline → Download JSON. Flip to Zendesk to
   show `dispatch_path` + internal note.

Press **F** to advance the fire — open equations shrink and turn red live.

## Dispatch rules (priority order)

| rule | condition | path |
|------|-----------|------|
| R0 | informational only, not trapped | `auto_answered` |
| R1 | trapped or injured | `fire_rescue` |
| R3 | evacuated + medical need | `accessible_shelter` |
| R4 | evacuated, no special need | `standard` |
| R2 | can't self-evacuate before fire, or time-to-impact < 0 | `transport_assist` |
| R5 | can self-evacuate in time | `standard` |

Extraction failures fail **toward safety**: any danger keyword with an untrusted
model → `needs_human_review` in the rescue lane.

## Security

All hardening lives in [`app/security.py`](app/security.py) (stdlib only — no new deps, no build step).

| # | Concern | Protection |
|---|---------|-----------|
| 1 | **Rate limits** (cost + bandwidth) | Per-IP token buckets in middleware. `/api/submit` (spends OpenAI+Zendesk money): burst 10, ~15/min. `/api/seed`+`/api/fire`: 12 burst. `/api/state` polling: 120 burst. Over budget → `429` + `Retry-After`. |
| 2 | **Exposed API keys** | Keys are server-side env only — never sent to the browser. [`.gitignore`](.gitignore) keeps `.env` out of git (only `.env.example` is tracked). Message text is sanitized before it reaches any log line. |
| 3 | **Exposed endpoints** | Every `/api/*` route is rate-limited. `/api/submit` enforces length limits (`422` on oversized). Bulk `/api/seed` (30 live calls) is **blocked in live mode** unless `BEACON_ALLOW_BULK_SEED=true`. |
| 4 | **Encryption / private data** | No database, no user credentials or billing stored. All outbound calls (Zendesk, OpenAI) are HTTPS/TLS. Secrets stay in the environment; response `Cache-Control: no-store`. |
| 5 | **Prompt injection** | *Architectural:* the LLM only fills a fixed fact schema (structured outputs) — a deterministic function makes every routing decision, so injection can't trigger an action. *Plus:* the system prompt marks the message untrusted; input is unicode-normalized and stripped of zero-width chars; and injection patterns (`ignore previous…`, role markers, `set physically_trapped…`) route the case to **human review** — fail toward safety. |
| 6 | **Webhooks / DNS / SSRF** | No inbound webhooks by design (the Zendesk poller is outbound-only, so there's no payload to forge). The Zendesk subdomain is validated against `^[a-z0-9-]+$` before it's placed in a URL, so a poisoned config value can't redirect requests to an attacker host. Security headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |

Tunable via env: `BEACON_ALLOW_BULK_SEED`. Limits live in `CATEGORY_LIMITS` in `app/security.py`.

> Note: per-IP limits use the socket peer address. Behind a reverse proxy, enforce
> limits at the proxy (or trust a validated `X-Forwarded-For`) so clients can't be
> collapsed to one IP.

## Honesty lines

- "The evidence is from the 2025 Eaton fire; every name and address here is fictional."
- The model never decides who gets rescued — it extracts facts. 25 lines of
  auditable rules make the call, and every call comes with a receipt.
