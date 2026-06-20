#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

MARKET_API  = "https://www.rewe.de/api/wksmarketselection/userselections"
STORES_FILE = Path(__file__).parent.parent / "public" / "stores.json"
OUTPUT_FILE = Path(__file__).parent.parent / "public" / "availability.json"

PRODUCTS = {
    "9444915": "Einzelpacket (7 Sticker)",
    "9446617": "Multipack (5 Tüten + 6 Sticker)",
    "7353919": "Mini-Multipack (4 Tüten + 4 Sticker)",
    "9443316": "Eco Blister (6 Tüten + 1 DFB)",
}

# Search URLs to try — /suche/ is a different path from /produkte/, CF may allow it
SEARCH_URLS = [
    "https://www.rewe.de/suche/?search=panini+sticker",
    "https://www.rewe.de/suche/?search=panini+wm+2026",
    "https://www.rewe.de/suche/?search=panini+fifa",
]

SET_MARKET_JS = """
async ({apiUrl, wwIdent}) => {
    try {
        const resp = await fetch(apiUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            body: JSON.stringify({selectedService: 'STATIONARY', customerZipCode: null, wwIdent: wwIdent})
        });
        return {ok: resp.status === 200 || resp.status === 201, status: resp.status};
    } catch(e) {
        return {ok: false, status: 0, error: String(e)};
    }
}
"""

# Probe a URL: return status, availability patterns, and context around "vorrätig"
PROBE_JS = """
async ({url}) => {
    try {
        const resp = await fetch(url, {credentials: 'include'});
        const text = await resp.text();
        const idx = text.indexOf('vorr');
        const context = idx >= 0 ? text.slice(Math.max(0, idx - 400), idx + 200) : null;
        const meist = (text.match(/Meist vorrätig/g) || []).length;
        const nicht  = (text.match(/Nicht vorrätig/g) || []).length;
        const m1 = (text.match(/availability:\\s*"[^"]+"/g) || []).slice(0, 4);
        const m2 = (text.match(/"availability":"[^"]+"/g) || []).slice(0, 4);
        const m3 = (text.match(/"stockStatus":"[^"]+"/g) || []).slice(0, 4);
        return {status: resp.status, len: text.length, meist, nicht, context, m1, m2, m3};
    } catch(e) {
        return {status: 0, error: String(e)};
    }
}
"""

BLOCKED_TYPES = {"image", "stylesheet", "font", "media"}


def main():
    stores = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(stores)} stores", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(locale="de-DE", viewport={"width": 1280, "height": 800})
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in BLOCKED_TYPES else route.continue_()
        ))

        print("Getting CF clearance...", flush=True)
        try:
            page.goto("https://www.rewe.de/", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
        except PWTimeout:
            print("  Warning: initial navigation timed out", flush=True)
        print(f"  Page URL: {page.url}", flush=True)

        # Probe: set market to Kastanienallee 38 (Mini-Multipack confirmed in stock there)
        # then test each search URL to see if /suche/ bypasses CF's /produkte/ block
        print("\n--- Probing /suche/ path (CF may not block this) ---", flush=True)
        sm = page.evaluate(SET_MARKET_JS, {"apiUrl": MARKET_API, "wwIdent": "1931651"})
        print(f"  Market → Kastanienallee 38: HTTP {sm.get('status')}", flush=True)

        working_url = None
        for url in SEARCH_URLS:
            r = page.evaluate(PROBE_JS, {"url": url})
            status = r.get("status")
            meist = r.get("meist", 0)
            nicht = r.get("nicht", 0)
            print(f"\n  {url}", flush=True)
            print(f"    HTTP {status}, len={r.get('len')}, 'Meist vorrätig'×{meist}, 'Nicht vorrätig'×{nicht}", flush=True)
            if r.get("context"):
                print(f"    Context: {r['context'][:500]}", flush=True)
            if r.get("m1"): print(f"    Pattern 1: {r['m1']}", flush=True)
            if r.get("m2"): print(f"    Pattern 2: {r['m2']}", flush=True)
            if r.get("m3"): print(f"    Pattern 3: {r['m3']}", flush=True)
            if status == 200 and (meist > 0 or nicht > 0 or r.get("m1") or r.get("m2")):
                working_url = url
                break

        print(f"\n  Working search URL: {working_url!r}", flush=True)
        print("--- End probe ---\n", flush=True)

        # Until we confirm the search approach works, write existing data unchanged
        # (don't overwrite availability.json with all-nulls)
        if OUTPUT_FILE.exists():
            print("Keeping existing availability.json unchanged (search approach not yet confirmed)", flush=True)
        else:
            # First run — write empty skeleton
            output = {
                "updated": datetime.now(timezone.utc).isoformat(),
                "products": PRODUCTS,
                "stores": [{**s, "available": None, "products": {pid: None for pid in PRODUCTS}} for s in stores],
            }
            OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")

        page.close()
        browser.close()

    print("Done — check probe output above to determine next step.", flush=True)


if __name__ == "__main__":
    main()
