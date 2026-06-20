#!/usr/bin/env python3
"""
Scrapes availability of Panini FIFA WC 2026 stickers (ID 9444915)
across all ~180 Berlin REWE stores using curl subprocess.

Flow per store:
  1. POST /api/wksmarketselection/userselections  → sets wksMarketsCookie
  2. GET  product page
  3. Parse: availability: "true" | "false" from XRD.tracking.extendPageData

Output: public/availability.json
"""
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

PRODUCT_URL = "https://www.rewe.de/produkte/panini-fifa-world-cup-2026-stickerpacket/9444915"
MARKET_API  = "https://www.rewe.de/api/wksmarketselection/userselections"
STORES_FILE = Path(__file__).parent.parent / "public" / "stores.json"
OUTPUT_FILE = Path(__file__).parent.parent / "public" / "availability.json"
COOKIE_JAR  = Path(tempfile.gettempdir()) / "rewe_cookies.txt"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

AVAIL_RE = re.compile(r'availability:\s*"([^"]+)"')


def curl(*args, check=False) -> tuple[int, bytes]:
    cmd = ["curl", "-s", "--max-time", "15", *args]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode, r.stdout


def refresh_cf_cookies():
    """Visit homepage to get fresh Cloudflare cookies."""
    curl(
        "-c", str(COOKIE_JAR),
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: de-DE,de;q=0.9",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: none",
        "-L", "-o", "/dev/null" if __import__("os").name != "nt" else "NUL",
        "https://www.rewe.de/",
    )


def set_market(ww_ident: str) -> bool:
    """POST to market selection API. Returns True on 200/201."""
    _, out = curl(
        "-c", str(COOKIE_JAR),
        "-b", str(COOKIE_JAR),
        "-H", f"User-Agent: {UA}",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json",
        "-H", "Origin: https://www.rewe.de",
        "-H", "Sec-Fetch-Dest: empty",
        "-H", "Sec-Fetch-Mode: cors",
        "-H", "Sec-Fetch-Site: same-origin",
        "-X", "POST",
        "-d", json.dumps({
            "selectedService": "STATIONARY",
            "customerZipCode": None,
            "wwIdent": ww_ident,
        }),
        "-w", "\n%{http_code}",
        MARKET_API,
    )
    lines = out.strip().split(b"\n")
    code = int(lines[-1]) if lines else 0
    return code in (200, 201)


def get_availability(ww_ident: str) -> str:
    """GET product page, return 'true'/'false'/'unknown'."""
    _, out = curl(
        "-b", str(COOKIE_JAR),
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: de-DE,de;q=0.9",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: none",
        "-L",
        "-w", "\n%{http_code}",
        PRODUCT_URL,
    )
    lines = out.split(b"\n")
    code = int(lines[-1]) if lines else 0
    if code != 200:
        return "unknown"
    html = b"\n".join(lines[:-1]).decode("utf-8", errors="replace")
    m = AVAIL_RE.search(html)
    if m:
        val = m.group(1).lower()
        return val if val in ("true", "false") else "unknown"
    return "unknown"


def main():
    stores = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(stores)} stores", flush=True)

    print("Getting fresh CF cookies...", flush=True)
    refresh_cf_cookies()

    results = []
    true_count = 0

    for i, store in enumerate(stores):
        ww_ident = store["id"]

        # Refresh CF cookies every 40 stores
        if i > 0 and i % 40 == 0:
            print(f"  [{i}] Refreshing CF cookies...", flush=True)
            refresh_cf_cookies()
            time.sleep(1)

        ok = set_market(ww_ident)
        if not ok:
            availability = "unknown"
        else:
            time.sleep(0.5)
            availability = get_availability(ww_ident)

        if availability == "true":
            true_count += 1

        label = "IN STOCK" if availability == "true" else availability
        print(f"[{i+1:3}/{len(stores)}] {ww_ident:8}  {store.get('address','')[:30]:30}  {label}", flush=True)

        results.append({**store, "available": availability == "true"})

        time.sleep(0.5)

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "stores": results,
    }
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. IN STOCK: {true_count}/{len(stores)}", flush=True)
    print(f"Saved to {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
