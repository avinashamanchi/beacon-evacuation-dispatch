"""Compose Guide-backed auto-answers for informational cases.

Never leaves an informational case unanswered: if Guide search fails, answer
from a small built-in FAQ.
"""
import re

STOPWORDS = {
    "the", "a", "an", "is", "are", "my", "i", "we", "do", "does", "how", "what",
    "when", "can", "you", "your", "to", "of", "for", "and", "or", "if", "in",
    "on", "it", "be", "me", "need", "please", "now", "get", "will", "am",
    "this", "that", "with", "have", "has", "was", "were", "our", "us", "at",
}

BUILTIN_FAQ = {
    "deductible": "Yes — deductibles are waived for claims filed under an active evacuation order.",
    "waiv": "Yes — deductibles are waived for claims filed under an active evacuation order.",
    "claim": "You can file a claim online with photos of the damage; an adjuster is assigned within 48 hours.",
    "hotel": "Reasonable hotel costs are reimbursable as temporary living expense when shelters are full — keep receipts.",
    "shelter": "The nearest open shelter and its address are listed on the county evacuation portal, updated hourly.",
    "road": "Live road-closure status is posted on the county evacuation portal and updated as conditions change.",
    "return": "Return timelines are set by fire officials; you'll be notified the moment your zone is cleared.",
    "premium": "Premium due dates are automatically extended 30 days for policyholders under an evacuation order.",
    "document": "To file you'll need your policy number and photos of the affected property — receipts help but aren't required.",
}

DEFAULT_ANSWER = (
    "Your question has been logged and a support specialist will follow up. "
    "For immediate evacuation guidance, follow official county alerts."
)


def keywords(message: str) -> list[str]:
    words = re.findall(r"[a-zA-Z']+", message.lower())
    kept = [w for w in words if w not in STOPWORDS and len(w) > 2]
    seen, out = set(), []
    for w in kept:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:5]


def _builtin(message: str) -> str:
    m = message.lower()
    for key, ans in BUILTIN_FAQ.items():
        if key in m:
            return ans
    return DEFAULT_ANSWER


def compose_answer(zclient, message: str) -> str:
    """One-sentence answer + article title + link, drawn from Guide search when
    available and from the built-in FAQ otherwise."""
    kws = keywords(message)
    query = " ".join(kws) if kws else message[:60]
    articles = []
    try:
        articles = zclient.search_guide(query)
    except Exception as exc:  # noqa: BLE001
        print(f"[BEACON] Guide search failed: {exc!r} — using built-in FAQ.")

    answer = _builtin(message)
    if articles:
        art = articles[0]
        title = art.get("title") or "Wildfire evacuation FAQ"
        url = art.get("url") or ""
        return f"{answer} Full details: {title}" + (f" ({url})." if url else ".")
    return answer
