"""
Probe script — discover correct CoinGlass v4 endpoint paths (extended).
Usage: python3 scripts/probe_coinglass_v4b.py
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

PATHS = [
    "/api-docs",
    "/v3/api-docs",
    "/v2/api-docs",
    "/actuator",
    "/actuator/mappings",
    "/api/bitcoin-indicator/mvrv-zscore",
    "/api/bitcoin-indicator/nupl",
    "/api/bitcoin_indicator/mvrv_zscore",
    "/api/bitcoin_indicator/nupl",
    "/api/on-chain/mvrv-zscore",
    "/api/on-chain/nupl",
    "/api/v1/mvrv-zscore",
    "/api/v1/nupl",
    "/api/v2/indicator/bitcoin_mvrv_zscore",
    "/api/v2/indicator/bitcoin_nupl",
    "/api/futures/bitcoin",
    "/api/index",
    "/api/health",
    "/api/bitcoin/onchain/mvrv-zscore",
    "/api/bitcoin/onchain/nupl",
    "/api/onchain/bitcoin/mvrv-zscore",
    "/api/onchain/bitcoin/nupl",
    "/api/data/bitcoin/mvrv-zscore",
    "/api/data/bitcoin/nupl",
]

for path in PATHS:
    url = BASE + path
    try:
        r = requests.get(url, headers=headers, timeout=8)
        body = r.text[:200].replace("\n", " ").strip()
        mark = " <<< HIT" if r.status_code in (200, 401, 403) else ""
        print(f"  [{r.status_code}]  {path}{mark}")
        if r.status_code in (200, 401, 403):
            print(f"         {body}")
    except Exception as exc:
        print(f"  [ERR]  {path} -> {exc}")
