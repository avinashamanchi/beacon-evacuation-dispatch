# Deploying BEACON

## Your three links (one deployment, three paths)

BEACON is one app. The three surfaces are three routes — deploying once gives
you all three:

| Surface | Path | Example URL |
|---------|------|-------------|
| Intake form | `/` | `https://<project>.vercel.app/` |
| Dispatch dashboard | `/dashboard` | `https://<project>.vercel.app/dashboard` |
| The film | `/film` | `https://<project>.vercel.app/film` |

(Three separate `.vercel.app` subdomains would mean three separate
deployments that can't share state — the wrong shape for this app. Three
paths on one deployment is the correct architecture and still gives you three
links.)

## ⚠️ Read this before you rely on a Vercel link for the live demo

BEACON keeps the running incident — cases, the fire countdown, the "Replay"
drip — in **server process memory**, advanced by **background timers**. That
is perfect for the local `uvicorn` server (one long-lived process) and is what
every judge sees when you run it locally.

Vercel (and any serverless host) is the opposite: each request may land on a
fresh, stateless instance, and background tasks don't survive past a response.
So on a raw Vercel deploy:

- ✅ The **film** cold-open, captions, and camera work (it drives the app, but
  the scripted beats still render).
- ✅ Any **single** stateless request (submit one message, see its routing).
- ❌ **Seed → poll** accumulation (the dashboard may show an empty board a
  poll later).
- ❌ **Replay incident** and **auto fire-advance** (background timers don't run).

**For a flawless live demo, run it locally** — that's the most reliable link
and needs no network:

```bash
uvicorn app.main:app --port 8000
# intake  http://localhost:8000/
# board   http://localhost:8000/dashboard
# film    http://localhost:8000/film
```

**To make Vercel bulletproof** the state must move off the server: either a
KV/Redis store (Vercel KV / Upstash) behind `app/state.py`, or — cleaner for a
single-presenter demo — move the case list + timers into the browser and make
the server a pure stateless `/api/route` function. That refactor is scoped but
not trivial; do it before trusting a Vercel URL on stage.

## Deploy steps (once you accept the caveat above)

### Option A — Git integration (recommended, auto-deploys on push)

1. Push this repo to GitHub (already done if you're reading this from GitHub).
2. In the Vercel dashboard: **Add New… → Project → Import** this repo.
3. Framework preset: **Other**. Root directory: repo root. Deploy.
4. Every `git push` redeploys automatically.

### Option B — Vercel CLI

```bash
npm i -g vercel
vercel login          # interactive — opens your browser
vercel --prod         # from the repo root
```

`vercel.json` rewrites every path to `api/index.py`, which exports the FastAPI
`app`. `requirements.txt` at the repo root supplies dependencies. Set
`DEMO_MODE=true` in the project's Environment Variables so it runs without
OpenAI/Zendesk creds.
