#!/usr/bin/env python3
import json
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

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

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


def curl(*args) -> tuple[int, bytes]:
    cmd = ["curl", "-s", "--max-time", "15", *args]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode, r.stdout


def refresh_cf_cookies():
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


def get_availability(product_url: str) -> bool | None:
    """Returns True (in stock), False (not in stock), or None (unknown)."""
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
        product_url,
    )
    lines = out.split(b"\n")
    code = int(lines[-1]) if lines else 0
    if code != 200:
        return None
    html = b"\n".join(lines[:-1]).decode("utf-8", errors="replace")
    m = AVAIL_RE.search(html)
    if m:
        val = m.group(1).lower()
        if val == "true":
            return True
        if val == "false":
            return False
    return None


def debug_first_store(stores):
    print("DEBUG: testing first store...", flush=True)
    set_market(stores[0]["id"])
    time.sleep(0.5)
    for pid, info in PRODUCTS.items():
        _, out = curl(
            "-b", str(COOKIE_JAR),
            "-H", f"User-Agent: {UA}",
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "Accept-Language: de-DE,de;q=0.9",
            "-H", "Sec-Fetch-Dest: document", "-H", "Sec-Fetch-Mode: navigate",
            "-H", "Sec-Fetch-Site: none", "-L",
            "-w", "\n%{http_code}", info["url"],
        )
        lines = out.split(b"\n")
        code = int(lines[-1]) if lines else 0
        html = b"\n".join(lines[:-1]).decode("utf-8", errors="replace")
        m = AVAIL_RE.search(html)
        print(f"  {pid}: HTTP {code}, len={len(html)}, avail={m.group(1) if m else 'NO MATCH'}", flush=True)
        time.sleep(0.3)
    jar = Path(str(COOKIE_JAR))
    print(f"  cookie jar exists={jar.exists()}, content:\n{jar.read_text(errors='replace')[-300:] if jar.exists() else 'MISSING'}", flush=True)


def main():
    stores = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(stores)} stores, {len(PRODUCTS)} products each", flush=True)

    print("Getting fresh CF cookies...", flush=True)
    refresh_cf_cookies()
    debug_first_store(stores)

    results = []
    stores_with_any = 0

    for i, store in enumerate(stores):
        ww_ident = store["id"]

        if i > 0 and i % 40 == 0:
            print(f"  [{i}] Refreshing CF cookies...", flush=True)
            refresh_cf_cookies()
            time.sleep(1)

        ok = set_market(ww_ident)
        if not ok:
            product_avail = {pid: None for pid in PRODUCTS}
            any_in_stock = False
        else:
            time.sleep(0.3)
            product_avail = {}
            for pid, info in PRODUCTS.items():
                product_avail[pid] = get_availability(info["url"])
                time.sleep(0.3)
            any_in_stock = any(v is True for v in product_avail.values())

        if any_in_stock:
            stores_with_any += 1

        in_stock_names = [PRODUCTS[pid]["name"] for pid, v in product_avail.items() if v is True]
        label = ", ".join(in_stock_names) if in_stock_names else ("unbekannt" if not ok else "nichts")
        print(f"[{i+1:3}/{len(stores)}] {ww_ident:8}  {store.get('address','')[:28]:28}  {label}", flush=True)

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
    print(f"Saved to {OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
