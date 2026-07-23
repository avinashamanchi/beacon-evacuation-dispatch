"""Vercel serverless entrypoint.

Vercel's Python runtime serves the ASGI `app` exported here. All routes are
rewritten to this function via vercel.json.

IMPORTANT — read DEPLOY.md: BEACON keeps its demo state in process memory with
background timers. Serverless instances are ephemeral, so the live/stateful
demo (Replay, auto fire-advance, seed-then-poll) is NOT reliable here without
the client-state refactor described in DEPLOY.md. The film's scripted beats
and any single stateless request work; the accumulating dashboard does not.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402  (re-exported for the Vercel runtime)
