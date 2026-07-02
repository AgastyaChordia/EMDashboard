"""
Pulls macro indicators (GDP growth, inflation, current account, debt,
unemployment) from the World Bank API. Free, no key needed.

Annual frequency -- this is trend/context data, not something that moves
week to week. It's what your AI commentary layer compares current market
moves against ("inflation is still running above the 5y average" etc).
"""
import sys
import time
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import requests
import pandas as pd

from config import WORLDBANK_COUNTRIES, WORLDBANK_INDICATORS
from db import upsert_macro, init_schema

BASE_URL = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"

# The World Bank API is free but flaky -- individual requests time out under
# load. Retry a few times with backoff before giving up on a series.
RETRIES = 3
TIMEOUT = 60


def fetch_indicator(country_code: str, indicator_code: str) -> list:
    url = BASE_URL.format(country=country_code, indicator=indicator_code)
    last_err = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(url, params={"format": "json", "per_page": 100},
                                timeout=TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            if len(payload) < 2 or payload[1] is None:
                return []
            return payload[1]
        except requests.exceptions.Timeout as e:
            last_err = e
            time.sleep(2 * (attempt + 1))  # 2s, 4s backoff between retries
    raise last_err


def run():
    init_schema()
    rows = []
    failures = []
    for country_name, country_code in WORLDBANK_COUNTRIES.items():
        for indicator_name, indicator_code in WORLDBANK_INDICATORS.items():
            try:
                records = fetch_indicator(country_code, indicator_code)
                if not records:
                    failures.append((f"{country_name}/{indicator_name}",
                                     indicator_code, "no data for this country"))
                    continue
                for rec in records:
                    if rec.get("value") is None:
                        continue
                    rows.append({
                        "country": country_name,
                        "indicator": indicator_name,
                        "date": f"{rec['date']}-01-01",
                        "value": rec["value"],
                        "source": "worldbank",
                    })
            except Exception as e:
                print(f"  [error] {country_name}/{indicator_name}: {e}")
                failures.append((f"{country_name}/{indicator_name}", indicator_code, str(e)))

    df = pd.DataFrame(rows)
    upsert_macro(df)
    print(f"Wrote {len(df)} macro observations across "
          f"{len(WORLDBANK_COUNTRIES)} countries and {len(WORLDBANK_INDICATORS)} indicators")

    total = len(WORLDBANK_COUNTRIES) * len(WORLDBANK_INDICATORS)
    print("\n" + "=" * 60)
    if not failures:
        print(f"World Bank: all {total} country/indicator series fetched OK.")
    else:
        print(f"World Bank: {len(failures)} of {total} country/indicator series had no data / FAILED:")
        for label, code, reason in failures:
            print(f"  - {label:<32} {code:<22} {reason}")
    print("=" * 60)


if __name__ == "__main__":
    run()
