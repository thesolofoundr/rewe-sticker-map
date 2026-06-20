#!/usr/bin/env python3
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests as cf_requests

MARKET_API  = "https://www.rewe.de/api/wksmarketselection/userselections"
STORES_FILE = Path(__file__).parent.parent / "public" / "stores.json"
OUTPUT_FILE = Path(__file__).parent.parent / "public" / "availability.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

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

HEADERS_HTML = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

HEADERS_API = {
    "User-Agent": UA,
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.rewe.de",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Session maintains cookies automatically (like a real browser)
session = cf_requests.Session(impersonate="chrome124")


def refresh_cf_cookies():
    try:
        session.get("https://www.rewe.de/", headers=HEADERS_HTML, timeout=15)
    except Exception as e:
        print(f"  CF refresh error: {e}", flush=True)


def set_market(ww_ident: str) -> bool:
    try:
        r = session.post(
            MARKET_API,
            json={"selectedService": "STATIONARY", "customerZipCode": None, "wwIdent": ww_ident},
            headers=HEADERS_API,
            timeout=15,
        )
        return r.status_code in (200, 201)
    except Exception:
        return False


def get_availability(product_url: str) -> bool | None:
    try:
        r = session.get(product_url, headers=HEADERS_HTML, timeout=15)
        if r.status_code != 200:
            return None
        m = AVAIL_RE.search(r.text)
        if m:
            val = m.group(1).lower()
            if val == "true":
                return True
            if val == "false":
                return False
    except Exception:
        return None
    return None


def main():
    stores = json.loads(STORES_FILE.read_text(encoding="utf-8"))
    print(f"Loaded {len(stores)} stores, {len(PRODUCTS)} products each", flush=True)

    print("Getting fresh CF cookies...", flush=True)
    refresh_cf_cookies()

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


if __name__ == "__main__":
    main()
