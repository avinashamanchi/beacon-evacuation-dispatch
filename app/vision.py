"""Photo intake — EXIF geolocation and image analysis.

Same principle as the text pipeline: **vision extracts facts, it never decides.**
The deterministic router still makes every dispatch call.

Three location sources, in order of trust:
  1. EXIF GPS          exact, and free — the sender types nothing
  2. street sign OCR   messaging apps strip EXIF constantly; signs survive
  3. typed text        the existing path

Two analysis paths, both honest about what they are:
  * OpenAI vision  when a key is configured
  * offline heuristic  a real fire-glow colour measurement (no network, no
    faking) — it reports its own low confidence and is labelled in the receipt
"""
import io
import math
from typing import Optional

from pydantic import BaseModel

from app import config
from app.seeds import nearest_street

MAX_PHOTO_BYTES = 8 * 1024 * 1024
ALLOWED = {b"\xff\xd8\xff": "jpeg", b"\x89PNG\r\n\x1a\n": "png"}


class PhotoFacts(BaseModel):
    visible_flames: bool = False
    heavy_smoke: bool = False
    road_blocked: bool = False
    structures_burning: bool = False
    street_sign_text: str = ""
    people_visible: int = 0
    description: str = ""
    confidence: float = 0.0
    analysis_source: str = "none"   # openai_vision | offline_heuristic | none


def sniff_type(data: bytes) -> Optional[str]:
    for magic, kind in ALLOWED.items():
        if data.startswith(magic):
            return kind
    return None


# --- EXIF --------------------------------------------------------------------
def _rational(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return v.numerator / v.denominator
        except Exception:  # noqa: BLE001
            return 0.0


def read_exif(data: bytes) -> dict:
    """Pull GPS + capture time. Never raises — a corrupt header just yields {}."""
    out = {"lat": None, "lng": None, "taken_at": None, "has_gps": False}
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return out
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        if not exif:
            return out
        tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        out["taken_at"] = str(tags.get("DateTimeOriginal") or tags.get("DateTime") or "") or None

        gps_ifd = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else None
        if gps_ifd:
            g = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
            def _dms(val, ref, neg):
                d = _rational(val[0]) + _rational(val[1]) / 60 + _rational(val[2]) / 3600
                return -d if str(ref).upper().startswith(neg) else d
            if g.get("GPSLatitude") and g.get("GPSLongitude"):
                out["lat"] = _dms(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"), "S")
                out["lng"] = _dms(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"), "W")
                out["has_gps"] = True
    except Exception:  # noqa: BLE001 — malformed EXIF must never break intake
        pass
    return out


def locate(data: bytes) -> dict:
    """Resolve a photo to a street. Reports which source won, and why."""
    exif = read_exif(data)
    if exif["has_gps"]:
        name, km = nearest_street(exif["lat"], exif["lng"])
        if name:
            return {"street": name, "source": "exif_gps", "km": round(km, 2),
                    "taken_at": exif["taken_at"], "lat": exif["lat"], "lng": exif["lng"]}
        return {"street": None, "source": "exif_gps_off_map", "km": round(km, 1),
                "taken_at": exif["taken_at"], "lat": exif["lat"], "lng": exif["lng"]}
    return {"street": None, "source": "no_exif", "km": None,
            "taken_at": exif["taken_at"], "lat": None, "lng": None}


# --- Analysis ----------------------------------------------------------------
VISION_PROMPT = """You are looking at a photo sent to a wildfire evacuation support line.
Extract ONLY what is visibly present. Never infer urgency, never rank severity,
never recommend an action. If something is not visible, use the schema default.
Read any street sign or house number exactly as printed into street_sign_text.
Report people_visible as a count of people you can actually see."""


def analyze(data: bytes) -> PhotoFacts:
    if not config.USE_FALLBACK_EXTRACTION:
        try:
            return _openai_vision(data)
        except Exception as exc:  # noqa: BLE001
            print(f"[BEACON] vision failed: {exc!r} — using offline heuristic.")
    return _offline_heuristic(data)


def _openai_vision(data: bytes) -> PhotoFacts:
    import base64
    from openai import OpenAI

    b64 = base64.b64encode(data).decode()
    kind = sniff_type(data) or "jpeg"
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    completion = client.beta.chat.completions.parse(
        model=config.OPENAI_MODEL,
        temperature=0,
        max_tokens=500,
        messages=[
            {"role": "system", "content": VISION_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/{kind};base64,{b64}"}},
            ]},
        ],
        response_format=PhotoFacts,
    )
    facts = completion.choices[0].message.parsed or PhotoFacts()
    facts.analysis_source = "openai_vision"
    return facts


def _offline_heuristic(data: bytes) -> PhotoFacts:
    """A real measurement, not a canned answer: what fraction of the frame sits
    in the fire-glow hue band, and how washed out (smoke) is the rest.

    Deliberately low confidence — it can see glow, it cannot read a street sign.
    """
    try:
        from PIL import Image
    except ImportError:
        return PhotoFacts(description="no image library available", analysis_source="none")
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((96, 96))
        raw = img.tobytes()
        px = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]
        if not px:
            return PhotoFacts(analysis_source="offline_heuristic")

        fire = smoke = 0
        for r, g, b in px:
            mx, mn = max(r, g, b), min(r, g, b)
            sat = 0 if mx == 0 else (mx - mn) / mx
            # fire glow: red-dominant, strongly saturated, bright
            if r > 110 and r > b + 45 and g < r and sat > 0.35:
                fire += 1
            # smoke: desaturated mid-to-bright grey/brown haze
            elif sat < 0.22 and 70 < mx < 225:
                smoke += 1
        n = len(px)
        fire_ratio, smoke_ratio = fire / n, smoke / n
        flames = fire_ratio > 0.12
        heavy_smoke = smoke_ratio > 0.45
        return PhotoFacts(
            visible_flames=flames,
            heavy_smoke=heavy_smoke,
            structures_burning=fire_ratio > 0.28,
            description=(f"offline colour analysis — {round(fire_ratio * 100)}% of frame in "
                         f"fire-glow range, {round(smoke_ratio * 100)}% haze"),
            confidence=0.4 if (flames or heavy_smoke) else 0.25,
            analysis_source="offline_heuristic",
        )
    except Exception as exc:  # noqa: BLE001
        return PhotoFacts(description=f"unreadable image ({exc!r})",
                          analysis_source="offline_heuristic")
