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
    "9444915": {
        "name": "Einzelpacket (7 Sticker)",
        "url": "https://www.rewe.de/produkte/panini-fifa-world-cup-2026-stickerpacket/9444915",
    },
    "9446617": {
        "name": "Multipack (5 Tüten + 6 Sticker)",
        "url": "https://www.rewe.de/produkte/panini-fifa-world-cup-2026-sammelsticker-multipack-5-tueten-6-sticker/9446617",
    },
    "7353919": {
        "name": "Mini-Multipack (4 Tüten + 4 Sticker)",
        "url": "https://www.rewe.de/produkte/panini-fifa-world-cup-2026-sammelsticker-mini-multipack-4-tueten-4-sticker/7353919",
    },
    "9443316": {
        "name": "Eco Blister (6 Tüten + 1 DFB)",
        "url": "https://www.rewe.de/produkte/panini-fifa-world-cup-2026-sammelsticker-eco-blister-6-tueten-1-dfb-sticker/9443316",
    },
}

AVAIL_RE = re.compile(r'availability:\s*"([^"]+)"')

# Runs in real Chromium — same-origin POST, CF allows JS fetch to API endpoints
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

BLOCKED_TYPES = {"image", "stylesheet", "font", "media"}


def main():
    stores = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(stores)} stores, {len(PRODUCTS)} products each", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            locale="de-DE",
            viewport={"width": 1280, "height": 800},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()
        # Block images/CSS/fonts so page.goto() only waits for the HTML
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
        relevant = [c["name"] for c in context.cookies() if any(k in c["name"].lower() for k in ("cf", "wks", "websitebot"))]
        print(f"  Cookies: {relevant}", flush=True)

        results = []
        stores_with_any = 0

        for i, store in enumerate(stores):
            ww_ident = store["id"]

            # POST via page.evaluate — CF allows JS fetch to API endpoints (Sec-Fetch-Dest: empty is fine for APIs)
            ok = False
            try:
                sm = page.evaluate(SET_MARKET_JS, {"apiUrl": MARKET_API, "wwIdent": ww_ident})
                ok = sm.get("ok", False)
                if not ok:
                    print(f"  [{i+1}] set_market HTTP {sm.get('status')} error={sm.get('error', '')}", flush=True)
                elif i < 2:
                    print(f"  [{i+1}] set_market OK (HTTP {sm.get('status')})", flush=True)
            except Exception as e:
                print(f"  [{i+1}] set_market exception: {e}", flush=True)

            if not ok:
                product_avail = {pid: None for pid in PRODUCTS}
                any_in_stock = False
            else:
                product_avail = {}
                for pid, info in PRODUCTS.items():
                    avail = None
                    try:
                        # page.goto sends Sec-Fetch-Dest: document — CF allows this for HTML pages
                        resp = page.goto(info["url"], wait_until="domcontentloaded", timeout=15000)
                        if resp and resp.ok:
                            html = page.content()
                            m = AVAIL_RE.search(html)
                            raw = m.group(1) if m else None
                            if raw == "true":
                                avail = True
                            elif raw == "false":
                                avail = False
                            if i < 2:
                                print(f"    {pid}: HTTP {resp.status}, avail={raw!r}", flush=True)
                        elif resp:
                            if i < 5:
                                print(f"    [{i+1}] {pid}: HTTP {resp.status}", flush=True)
                    except PWTimeout:
                        if i < 5:
                            print(f"    [{i+1}] {pid}: timeout", flush=True)
                    except Exception as e:
                        print(f"    [{i+1}] {pid} exception: {e}", flush=True)
                    product_avail[pid] = avail
                any_in_stock = any(v is True for v in product_avail.values())

            if any_in_stock:
                stores_with_any += 1

            in_stock_names = [PRODUCTS[pid]["name"] for pid, v in product_avail.items() if v is True]
            label = ", ".join(in_stock_names) if in_stock_names else ("unbekannt" if not ok else "nichts")
            print(f"[{i+1:3}/{len(stores)}] {ww_ident:8}  {store.get('address', '')[:28]:28}  {label}", flush=True)

            results.append({
                **store,
                "available": any_in_stock,
                "products": {pid: v for pid, v in product_avail.items()},
            })

        page.close()
        browser.close()

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "products": {pid: info["name"] for pid, info in PRODUCTS.items()},
        "stores": results,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Stores with any product in stock: {stores_with_any}/{len(stores)}", flush=True)


if __name__ == "__main__":
    main()
