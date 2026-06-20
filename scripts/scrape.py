#!/usr/bin/env python3
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

MARKET_API  = "https://www.rewe.de/api/wksmarketselection/userselections"
STORES_FILE = Path(__file__).parent.parent / "public" / "stores.json"
OUTPUT_FILE = Path(__file__).parent.parent / "public" / "availability.json"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
AVAIL_RE = re.compile(r'availability:\s*"([^"]+)"')

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


def parse_availability(html: str) -> bool | None:
    m = AVAIL_RE.search(html)
    if not m:
        return None
    val = m.group(1).lower()
    if val == "true":
        return True
    if val == "false":
        return False
    return None


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
            user_agent=UA,
            locale="de-DE",
            viewport={"width": 1280, "height": 800},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Visit homepage once to establish CF clearance cookie
        print("Getting CF clearance...", flush=True)
        page = context.new_page()
        try:
            page.goto("https://www.rewe.de/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
        except PWTimeout:
            pass
        page.close()
        print("  CF clearance established", flush=True)

        results = []
        stores_with_any = 0

        for i, store in enumerate(stores):
            ww_ident = store["id"]

            # Select store — same Chromium TLS stack, so CF allows it
            ok = False
            try:
                resp = context.request.post(
                    MARKET_API,
                    data={
                        "selectedService": "STATIONARY",
                        "customerZipCode": None,
                        "wwIdent": ww_ident,
                    },
                    headers={
                        "Accept": "application/json",
                        "Origin": "https://www.rewe.de",
                        "Sec-Fetch-Dest": "empty",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Site": "same-origin",
                    },
                    timeout=15000,
                )
                ok = resp.status in (200, 201)
                if i < 2:
                    print(f"  set_market HTTP {resp.status}", flush=True)
            except Exception as e:
                print(f"  [{i+1}] set_market error: {e}", flush=True)

            if not ok:
                product_avail = {pid: None for pid in PRODUCTS}
                any_in_stock = False
            else:
                time.sleep(0.2)
                product_avail = {}
                for pid, info in PRODUCTS.items():
                    avail = None
                    try:
                        r = context.request.get(
                            info["url"],
                            headers={
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Accept-Language": "de-DE,de;q=0.9",
                                "Referer": "https://www.rewe.de/",
                                "Sec-Fetch-Dest": "document",
                                "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Site": "same-origin",
                            },
                            timeout=15000,
                        )
                        if r.status == 200:
                            avail = parse_availability(r.text())
                        else:
                            print(f"    HTTP {r.status} for {pid}", flush=True)
                    except Exception as e:
                        print(f"    error for {pid}: {e}", flush=True)
                    product_avail[pid] = avail
                    time.sleep(0.2)
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

            time.sleep(0.3)

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
