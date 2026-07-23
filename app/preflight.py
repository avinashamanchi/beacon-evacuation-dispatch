"""Venue preflight: verify every integration before you're on stage.

Run:  python -m app.preflight
Exit code 0 = ready to demo; 1 = something needs attention.
Also served as GET /api/health for the dashboard/dev tools.
"""
from app import config


def run_checks() -> dict:
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    check("demo_mode", True,
          "DEMO_MODE=true — fully offline, mock Zendesk + keyword extraction"
          if config.DEMO_MODE else "DEMO_MODE=false — live integrations expected")

    if config.DEMO_MODE:
        check("zendesk", True, "mocked (in-memory tickets, IDs from 4200)")
        check("openai", True, "mocked (deterministic keyword extractor)")
    else:
        check("openai_key", config.OPENAI_CONFIGURED,
              f"model={config.OPENAI_MODEL}" if config.OPENAI_CONFIGURED
              else "OPENAI_API_KEY missing — will fall back to keyword extraction")
        check("zendesk_creds", config.ZENDESK_CONFIGURED,
              f"subdomain={config.ZENDESK_SUBDOMAIN}" if config.ZENDESK_CONFIGURED
              else "ZENDESK_* missing — will fall back to mock client")
        if config.ZENDESK_CONFIGURED:
            from app.security import valid_subdomain
            check("zendesk_subdomain_format", valid_subdomain(config.ZENDESK_SUBDOMAIN),
                  "bare label, safe to interpolate into URL")
            # Live reachability probe (auth + network in one call).
            try:
                import httpx
                r = httpx.get(
                    f"https://{config.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/users/me.json",
                    auth=(f"{config.ZENDESK_EMAIL}/token", config.ZENDESK_API_TOKEN),
                    timeout=6.0,
                )
                authed = r.status_code == 200 and r.json().get("user", {}).get("id")
                check("zendesk_auth", bool(authed),
                      "token accepted" if authed else f"HTTP {r.status_code} — check email/token")
            except Exception as exc:  # noqa: BLE001
                check("zendesk_auth", False, f"unreachable: {exc!r}")
        check("dispatch_field_id", bool(config.ZENDESK_DISPATCH_FIELD_ID),
              f"id={config.ZENDESK_DISPATCH_FIELD_ID}" if config.ZENDESK_DISPATCH_FIELD_ID
              else "not set — custom field write-back will be skipped")

    # Photo intake stack
    try:
        import PIL  # noqa: F401
        check("photo_imaging", True, "Pillow available (EXIF + offline analysis)")
    except ImportError:
        check("photo_imaging", False, "Pillow missing — pip install -r requirements.txt")

    import os as _os
    _static = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "static")
    _demo = _os.path.join(_static, "demo")
    _pack = sorted(f for f in _os.listdir(_demo)) if _os.path.isdir(_demo) else []
    check("demo_photo_pack", len(_pack) >= 4,
          f"{len(_pack)} bundled photos" if _pack
          else "missing — run: python -m tools.make_demo_photos")

    _uploads = _os.path.join(_static, "uploads")
    try:
        _os.makedirs(_uploads, exist_ok=True)
        _probe = _os.path.join(_uploads, ".probe")
        open(_probe, "w").close(); _os.remove(_probe)
        check("uploads_writable", True, _uploads)
    except OSError as exc:
        check("uploads_writable", False, f"cannot write uploads dir: {exc!r}")

    check("fire_eta", config.FIRE_ETA_MINUTES > 0,
          f"{config.FIRE_ETA_MINUTES} minutes at incident start")
    check("crew_counts", isinstance(config.CREW_COUNTS, dict) and config.CREW_COUNTS,
          str(config.CREW_COUNTS))

    ready = all(c["ok"] for c in checks)
    return {"ready": ready, "checks": checks}


def main() -> int:
    result = run_checks()
    width = max(len(c["name"]) for c in result["checks"]) + 2
    print("\nBEACON preflight\n" + "=" * 40)
    for c in result["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"  [{mark}] {c['name']:<{width}} {c['detail']}")
    print("=" * 40)
    print("READY TO DEMO ✅\n" if result["ready"] else "NOT READY — fix the FAILs above ❌\n")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
