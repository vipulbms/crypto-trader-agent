"""
Probe script — discover correct CoinGlass v4 endpoint paths for MVRV Z-Score and NUPL.
Usage: python3 scripts/probe_coinglass_v4.py
"""
import os
import sys

import requests

sys.path.insert(0, ".")

API_KEY = os.getenv("COINGLASS_API_KEY", "").strip()
BASE = "https://open-api-v4.coinglass.com"

headers = {
    "Accept": "application/json",
    "CG-API-KEY": API_KEY,
    "coinglassSecret": API_KEY,
}

print(f"Base URL : {BASE}")
print(f"API key  : {'SET (' + API_KEY[:6] + '...' + ')' if API_KEY else 'NOT SET'}")
print()

# Candidate paths drawn from CoinGlass v4 API docs patterns
PATHS = [
    # On-chain section (most likely home for MVRV/NUPL)
    "/api/on-chain/bitcoin/mvrv-zscore",
    "/api/on-chain/bitcoin/nupl",
    "/api/on_chain/bitcoin/mvrv_zscore",
    "/api/on_chain/bitcoin/nupl",
    # Indicator section
    "/api/indicator/bitcoin-mvrv-zscore",
    "/api/indicator/bitcoin-nupl",
    "/api/indicator/bitcoin_mvrv_zscore",
    "/api/indicator/bitcoin_nupl",
    # Versioned public paths
    "/public/v4/indicator/bitcoin_mvrv_zscore",
    "/public/v4/indicator/bitcoin_nupl",
    "/api/v4/indicator/bitcoin_mvrv_zscore",
    "/api/v4/indicator/bitcoin_nupl",
    # Root discovery
    "/api/bitcoin/mvrv-zscore",
    "/api/bitcoin/nupl",
    # Swagger / docs
    "/swagger",
    "/swagger.json",
    "/openapi.json",
    "/api/docs",
]

MAX_SNIPPET = 200

for path in PATHS:
    url = BASE + path
    try:
        r = requests.get(url, headers=headers, timeout=8)
        body = r.text.replace("\n", " ").strip()[:MAX_SNIPPET]
        marker = "<<< HIT" if r.status_code in (200, 401, 403) else ""
        print(f"  [{r.status_code}]  {path}  {marker}")
        if r.status_code in (200, 401, 403):
            print(f"         body: {body}")
    except Exception as exc:
        print(f"  [ERR]  {path}  -> {exc}")
