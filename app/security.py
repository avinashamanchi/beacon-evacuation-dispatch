"""Security helpers for BEACON: input hardening, prompt-injection detection,
outbound-target validation, and an in-memory token-bucket rate limiter.

No external dependencies — everything here is stdlib so it works with the
project's zero-build-step constraint.
"""
import re
import threading
import time
import unicodedata

# --- Input validation limits (bandwidth / cost / DoS bounds) -----------------
MAX_NAME_LEN = 120
MAX_MESSAGE_LEN = 2000  # also caps tokens sent to the LLM

# Zero-width / invisible characters used to smuggle hidden instructions.
_INVISIBLE = dict.fromkeys(
    map(ord, "​‌‍⁠﻿‎‏‪‫‬‭‮"),
    None,
)


def sanitize_text(s: str) -> str:
    """Normalize unicode homoglyph tricks, strip invisible/control characters,
    and bound length. Applied before a message is stored, extracted, or logged."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_INVISIBLE)
    s = "".join(
        ch for ch in s
        if ch in ("\n", "\t") or (ord(ch) >= 32 and not unicodedata.category(ch).startswith("C"))
    )
    return s.strip()


# --- Prompt-injection heuristics --------------------------------------------
# Defense in depth. The primary defense is architectural: the LLM only fills a
# fixed fact schema and a deterministic function makes the routing decision, so
# an injected message cannot trigger an action — at worst it flips a fact. When
# these patterns match we fail toward safety and route to human review.
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|the\s+)?(previous|prior|above|earlier)",
    r"disregard\s+(all\s+|the\s+|your\s+)?(previous|prior|above|instruction)",
    r"forget\s+(all\s+|everything\s+|your\s+)?(previous|prior|instruction)",
    r"you\s+are\s+now\b",
    r"new\s+instructions?\s*:",
    r"system\s+prompt",
    r"developer\s+mode",
    r"jailbreak",
    r"prompt\s+injection",
    r"</?(system|assistant|user)\s*>",
    r"<\|.*?\|>",
    r"begin\s+system",
    r"override\s+.{0,24}(rule|instruction|routing|dispatch)",
    r"set\s+(physically_trapped|is_informational_only|dispatch_path|can_self_evacuate)",
    r"route\s+(this\s+)?to\s+(auto_answered|standard)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE | re.DOTALL)


def detect_injection(message: str) -> bool:
    return bool(_INJECTION_RE.search(message or ""))


# --- Outbound target validation (SSRF hardening) ----------------------------
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def valid_subdomain(sub: str) -> bool:
    """Only a bare Zendesk subdomain label is allowed in the base URL, so a
    poisoned config value can't redirect requests to an attacker host."""
    return bool(sub) and bool(_SUBDOMAIN_RE.match(sub))


# --- Token-bucket rate limiter ----------------------------------------------
class RateLimiter:
    """Per-key token bucket. Thread-safe, in-memory, monotonic-clock based."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, capacity: int, refill_per_sec: float):
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * refill_per_sec)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False, (1.0 - tokens) / refill_per_sec
            self._buckets[key] = (tokens - 1.0, now)
            return True, 0.0


limiter = RateLimiter()

# (capacity = burst, refill_per_sec = sustained rate)
CATEGORY_LIMITS = {
    "submit": (10, 0.25),   # costs money: burst 10, ~15/min sustained
    "mutate": (12, 0.5),    # seed / fire advance
    "read": (120, 5.0),     # /api/state polling — generous for dashboards
}


def categorize(path: str, method: str):
    if method in ("GET", "HEAD") and path == "/api/state":
        return "read"
    if path == "/api/submit":
        return "submit"
    if path.startswith("/api/seed") or path in ("/api/fire/advance", "/api/simulate", "/api/reset"):
        return "mutate"
    if path.startswith("/api/case/") and method in ("PATCH", "POST"):
        return "mutate"
    if path == "/api/learning/approve":
        return "mutate"
    if path.startswith("/api/"):
        return "read"
    return None  # pages + static assets are not rate-limited
