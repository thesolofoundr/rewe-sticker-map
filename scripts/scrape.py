#!/usr/bin/env python3
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

MARKET_API  = "https://www.rewe.de/api/wksmarketselection/userselections"
STORES_FILE = Path(__file__).parent.parent / "public" / "stores.json"
OUTPUT_FILE = Path(__file__).parent.parent / "public" / "availability.json"
COOKIE_JAR  = Path(tempfile.gettempdir()) / "rewe_cookies.txt"

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
AVAIL_RE = re.compile(r'availability:\s*"([^"]+)"')
DEV_NULL = "NUL" if os.name == "nt" else "/dev/null"

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


def curl(*args) -> tuple[int, bytes]:
    r = subprocess.run(["curl", "-s", "--max-time", "15", *args], capture_output=True)
    return r.returncode, r.stdout


def bootstrap_cookies():
    """Launch real Chromium to solve CF JS challenge and write all cookies to jar."""
    print("Launching Chromium to get CF clearance...", flush=True)
    from playwright.sync_api import sync_playwright

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
        page = context.new_page()
        try:
            page.goto("https://www.rewe.de/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  Page load note: {e}", flush=True)

        cookies = context.cookies()
        browser.close()

    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c.get("domain", "")
        incl_sub = "TRUE" if domain.startswith(".") else "FALSE"
        if not domain.startswith("."):
            domain = "." + domain
        expires = max(0, int(c.get("expires", 0) or 0))
        secure = "TRUE" if c.get("secure") else "FALSE"
        lines.append(
            f"{domain}\t{incl_sub}\t{c.get('path', '/')}\t{secure}\t{expires}\t{c['name']}\t{c['value']}"
        )
    COOKIE_JAR.write_text("\n".join(lines) + "\n")

    cf_cookies = [c["name"] for c in cookies if "cf" in c["name"].lower()]
    print(f"  Got {len(cookies)} cookies. CF-related: {cf_cookies}", flush=True)


def set_market(ww_ident: str) -> bool:
    _, out = curl(
        "-c", str(COOKIE_JAR), "-b", str(COOKIE_JAR),
        "-H", f"User-Agent: {UA}",
        "-H", "Content-Type: application/json", "-H", "Accept: application/json",
        "-H", "Origin: https://www.rewe.de",
        "-H", "Sec-Fetch-Dest: empty", "-H", "Sec-Fetch-Mode: cors",
        "-H", "Sec-Fetch-Site: same-origin",
        "-X", "POST",
        "-d", json.dumps({"selectedService": "STATIONARY", "customerZipCode": None, "wwIdent": ww_ident}),
        "-w", "\n%{http_code}", MARKET_API,
    )
    lines = out.strip().split(b"\n")
    code = int(lines[-1]) if lines else 0
    return code in (200, 201)


def get_availability(product_url: str, _debug: bool = False) -> bool | None:
    _, out = curl(
        "-b", str(COOKIE_JAR), "-H", f"User-Agent: {UA}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: de-DE,de;q=0.9",
        "-H", "Sec-Fetch-Dest: document", "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: none", "-L",
        "-w", "\n%{http_code}", product_url,
    )
    lines = out.split(b"\n")
    code = int(lines[-1]) if lines else 0
    if code != 200:
        if _debug:
            print(f"      HTTP {code} — still blocked", flush=True)
        return None
    html = b"\n".join(lines[:-1]).decode("utf-8", errors="replace")
    if _debug:
        idx = html.find("availability")
        snippet = html[idx:idx+120] if idx >= 0 else "(not found in HTML)"
        print(f"      HTTP {code}, availability context: {snippet!r}", flush=True)
    m = AVAIL_RE.search(html)
    if m:
        val = m.group(1).lower()
        if val == "true":
            return True
        if val == "false":
            return False
    return None


def main():
    stores = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(stores)} stores, {len(PRODUCTS)} products each", flush=True)

    bootstrap_cookies()

    results = []
    stores_with_any = 0

    for i, store in enumerate(stores):
        ww_ident = store["id"]

        ok = set_market(ww_ident)
        if not ok:
            product_avail = {pid: None for pid in PRODUCTS}
            any_in_stock = False
        else:
            time.sleep(0.3)
            product_avail = {}
            debug_this = i < 2
            for pid, info in PRODUCTS.items():
                product_avail[pid] = get_availability(info["url"], _debug=debug_this)
                time.sleep(0.3)
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

        time.sleep(0.5)

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "products": {pid: info["name"] for pid, info in PRODUCTS.items()},
        "stores": results,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Stores with any product in stock: {stores_with_any}/{len(stores)}", flush=True)


if __name__ == "__main__":
    main()
