"""Seed data: fictional Cedar Canyon streets, noise tickets, scripted demos.

Every person, street, and address here is fictional. The town "Cedar Canyon,
CA" does not exist. No real victims' names or real addresses appear anywhere.
"""
import hashlib
import re

# 12 fictional streets -> (x%, y%) map coords. Several cluster in the NE near
# the fire origin (top-right of the map).
STREETS = {
    "cedar canyon rd": {"x": 34, "y": 61},
    "miner's bend": {"x": 66, "y": 26},
    "ridgeway loop": {"x": 72, "y": 33},
    "pine hollow ct": {"x": 61, "y": 22},
    "granite pass": {"x": 78, "y": 24},
    "old sawmill rd": {"x": 46, "y": 48},
    "sumac trail": {"x": 69, "y": 41},
    "redtail dr": {"x": 55, "y": 55},
    "quarry view ln": {"x": 41, "y": 37},
    "foxglove way": {"x": 28, "y": 47},
    "larkspur ct": {"x": 23, "y": 68},
    "stagecoach rd": {"x": 50, "y": 72},
}

# 30 routine messages. Several are written in a panicked tone on purpose so the
# contrast thesis — panic != danger — is visible right in the feed.
NOISE_TICKETS = [
    ("Marisol Trent", "Is my deductible waived if I file during the evacuation order?"),
    ("Dwayne Foss", "PLEASE I need my claim number RIGHT NOW my hands are shaking!!"),
    ("Priya Nandakumar", "When can we return to our home on Larkspur Ct? Any timeline?"),
    ("Colton Reyes", "How do I upload photos of my property for a claim?"),
    ("Bianca Ostrowski", "Will you reimburse a hotel if the shelters are full?"),
    ("Gerald Amoako", "URGENT!!! what documents do I need to file, everyone is leaving!!!"),
    ("Sunny Vphakdy", "Status of claim #44821 please, filed two days ago."),
    ("Renata Cho", "Do I need receipts for emergency supplies to be reimbursed?"),
    ("Ibrahim Salcedo", "My premium is due tomorrow, can I get an extension?"),
    ("Tess McGrail", "Which roads are closed heading out of Redtail Dr right now?"),
    ("Ozzie Lindqvist", "HELP the sky is orange and I can't find my policy number!!!"),
    ("Harriet Baugh", "Is smoke damage covered even if the house doesn't burn?"),
    ("Marcus Delacroix", "Where is the nearest shelter to Foxglove Way?"),
    ("Lena Postlethwaite", "Can I add my detached garage to the existing policy today?"),
    ("Ruben Achterberg", "How long does a claim take to process during a disaster?"),
    ("Fiona Trelawney", "I evacuated already, just want to confirm my claim is on file."),
    ("Desmond Actually-Okonkwo", "What's the phone number for roadside assistance?"),
    ("Aya Nakamura-Bell", "PANICKING — do I get a rental car covered while displaced??"),
    ("Grover Pinsky", "Can you email me a copy of my declarations page?"),
    ("Noor Al-Rashidi", "Does the policy cover spoiled food from the power outage?"),
    ("Ollie Whitcombe", "When will an adjuster be assigned to Quarry View Ln?"),
    ("Sabine Hollander", "URGENT what's my coverage limit I need to know NOW"),
    ("Teodoro Bax", "Can I file a claim online or does it have to be by phone?"),
    ("Wendy Kirkbride", "Is temporary living expense included in my plan?"),
    ("Hassan El-Amin", "How do I check if my mortgage lender is on the claim?"),
    ("Petra Osgood", "My neighbor said deductibles are waived — is that true?"),
    ("Cyrus Vandermolen", "Need a copy of last year's payment history for taxes."),
    ("Delphine Rousseau", "Can I still add flood coverage before the storm after the fire?"),
    ("Mordecai Flitwick", "HELP ME the alerts keep going off what do I even DO first??"),
    ("Ines Barrientos", "Confirming the mailing address on file is correct, thanks."),
]

# Scripted demo tickets: 1/2/3 from the runbook, 4 = the multilingual beat
# (non-English speakers are among the most at-risk in real evacuations).
DEMO_TICKETS = {
    4: (
        "Rosa Delgadillo",
        "Estamos atrapados en el coche, las llamas bloquean la salida de "
        "Miner's Bend. Somos dos personas.",
    ),
    1: (
        "Marisol Trent",
        "IS MY DEDUCTIBLE WAIVED?? I NEED AN ANSWER NOW, my whole street is evacuating!!!",
    ),
    2: (
        "Harriet Baugh",
        "My son and I both use wheelchairs. The house next door is on fire. "
        "I've called twice. We're at 41 Cedar Canyon Rd.",
    ),
    3: (
        "Marcus Delacroix",
        "Road out of Miner's Bend is blocked by flames, we're trapped in the car.",
    ),
}


# --- Fictional geographic frame ---------------------------------------------
# Cedar Canyon does not exist. These are SYNTHETIC anchor coordinates chosen so
# that EXIF GPS from a photo can be resolved to a street in the demo town. They
# are not, and must not be presented as, a real place.
ANCHOR_LAT, ANCHOR_LNG = 34.9000, -118.9000   # NW corner of the fictional map
SPAN_LAT, SPAN_LNG = 0.036, 0.043             # ~4 km box
MAX_INCIDENT_KM = 12.0                        # beyond this, photo is off-map


def street_latlng(name: str):
    c = STREETS.get(name)
    if not c:
        return None
    return (ANCHOR_LAT - (c["y"] / 100.0) * SPAN_LAT,
            ANCHOR_LNG + (c["x"] / 100.0) * SPAN_LNG)


def _km_between(a, b):
    """Equirectangular approximation — plenty accurate across a 4 km town."""
    import math
    lat1, lng1 = a
    lat2, lng2 = b
    x = math.radians(lng2 - lng1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * 6371.0


def nearest_street(lat: float, lng: float):
    """Resolve GPS to the nearest known street. Returns (name, km) or (None, km)
    when the photo was taken outside the incident area."""
    best, best_km = None, float("inf")
    for name in STREETS:
        d = _km_between((lat, lng), street_latlng(name))
        if d < best_km:
            best, best_km = name, d
    if best_km > MAX_INCIDENT_KM:
        return None, best_km
    return best, best_km


def find_street(location_text: str):
    """Return (name, coords) for the first street named in the text, else (None, None)."""
    lt = (location_text or "").lower()
    for name, coords in STREETS.items():
        if name in lt:
            return name, coords
    return None, None


def pin_for(case_id: str, location_text: str) -> dict:
    """Street match -> its coords; otherwise a deterministic pseudo-random pin
    seeded by the case id so every case lands somewhere on the map."""
    _, coords = find_street(location_text)
    if coords:
        return {"x": float(coords["x"]), "y": float(coords["y"])}
    h = int(hashlib.md5(case_id.encode()).hexdigest(), 16)
    x = 15 + (h % 70)
    y = 20 + ((h // 70) % 60)
    return {"x": float(x), "y": float(y)}


def extract_location(message: str) -> str:
    """Return the street as written (with any leading house number), else ""."""
    m = message.lower()
    for name in STREETS:
        if name in m:
            pat = re.compile(r"(\d+\s+)?" + re.escape(name), re.IGNORECASE)
            match = pat.search(message)
            return match.group(0).strip() if match else name
    return ""
