"""
Pulls sovereign yields and credit spreads from FRED.

Needs a free API key: https://fred.stlouisfed.org/docs/api/api_key.html
Set it as an environment variable before running:
    export FRED_API_KEY=your_key_here
"""
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
from fredapi import Fred

from config import FRED_YIELDS, CREDIT_SPREADS_FRED
from db import upsert_prices, init_schema


def fetch_fred_series(series_map: dict, module: str, fred: Fred,
                      failures: list = None) -> pd.DataFrame:
    rows = []
    for asset_id, series_id in series_map.items():
        try:
            s = fred.get_series(series_id)
            s = s.dropna()
            if s.empty:
                print(f"  [warn] no data returned for {asset_id} ({series_id})")
                if failures is not None:
                    failures.append((asset_id, series_id, "no data returned"))
                continue
            for date, value in s.items():
                rows.append({
                    "asset_id": asset_id,
                    "module": module,
                    "date": date.date() if hasattr(date, "date") else date,
                    "open": value, "high": value, "low": value, "close": value,
                    "volume": 0,
                })
        except Exception as e:
            print(f"  [error] {asset_id} ({series_id}): {e}")
            if failures is not None:
                failures.append((asset_id, series_id, str(e)))
    return pd.DataFrame(rows)


def run():
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("FRED_API_KEY not set -- get a free key at "
              "https://fred.stlouisfed.org/docs/api/api_key.html and "
              "export FRED_API_KEY=... before running this.")
        return

    init_schema()
    fred = Fred(api_key=api_key)
    failures = []

    print("Fetching sovereign yields...")
    df = fetch_fred_series(FRED_YIELDS, "fixed_income_yields", fred, failures)
    upsert_prices(df)
    print(f"  wrote {len(df)} rows")

    print("Fetching credit spreads...")
    df = fetch_fred_series(CREDIT_SPREADS_FRED, "credit_spreads", fred, failures)
    upsert_prices(df)
    print(f"  wrote {len(df)} rows")

    total = len(FRED_YIELDS) + len(CREDIT_SPREADS_FRED)
    print("\n" + "=" * 60)
    if not failures:
        print(f"FRED: all {total} series fetched OK.")
    else:
        print(f"FRED: {len(failures)} of {total} series FAILED:")
        for asset_id, series_id, reason in failures:
            print(f"  - {asset_id:<20} {series_id:<18} {reason}")
    print("=" * 60)


if __name__ == "__main__":
    run()
