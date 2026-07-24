"""
Index valuation multiples (trailing PE, forward PE, CAPE) from the Siblis
Research free data API. No API key needed.

    GET {SIBLIS_API_BASE}/{TICKER}/{METRIC}
    -> {"data": [{"trading_day (EOD)": "2026-06-30", "value": 19.94}, ...]}

Roughly 8 semi-annual observations per ticker/metric. Only the three metrics in
config.VALUATION_METRICS work on the free tier; 'pe', 'eps', 'pb' and
'dividend-yield' either 400 or return nulls, so they're never requested.

Null values are skipped rather than stored as 0 -- e.g. N225 has no forward PE,
and that gap must stay a genuine blank all the way to the UI.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import requests

from config import SIBLIS_API_BASE, VALUATION_TICKERS, VALUATION_METRICS
from db import upsert_valuations, init_schema

DATE_KEY = "trading_day (EOD)"
SOURCE = "Siblis Research"
TIMEOUT = 30


def fetch_metric(ticker: str, metric: str, asset_id: str,
                 failures: list = None) -> list:
    """Fetch one (ticker, metric) pair. Returns a list of row dicts ready for
    db.upsert_valuations -- empty if the call fails or every value is null.
    Failures are appended to `failures` as (asset_id, metric, reason)."""
    url = f"{SIBLIS_API_BASE}/{ticker}/{metric}"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"  [error] {asset_id} ({ticker}/{metric}): {e}")
        if failures is not None:
            failures.append((asset_id, metric, str(e)))
        return []

    rows = []
    for rec in (payload.get("data") or []):
        day, value = rec.get(DATE_KEY), rec.get("value")
        if day is None or value is None:
            continue          # genuine gap -> no row, surfaces as NaN later
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        rows.append({
            "asset_id": asset_id,
            "metric": metric,
            "date": pd.to_datetime(day).date(),
            "value": value,
            "source": SOURCE,
        })
    if not rows:
        print(f"  [warn] no usable data for {asset_id} ({ticker}/{metric})")
        if failures is not None:
            failures.append((asset_id, metric, "no non-null values"))
    return rows


def run():
    """Fetch all metrics for all mapped tickers and upsert into DuckDB.
    Safe to re-run -- upserts by (asset_id, metric, date)."""
    init_schema()
    rows, failures = [], []
    for ticker, asset_id in VALUATION_TICKERS.items():
        print(f"Fetching valuations for {asset_id} ({ticker})...")
        for metric in VALUATION_METRICS:
            rows.extend(fetch_metric(ticker, metric, asset_id, failures))

    df = pd.DataFrame(rows)
    upsert_valuations(df)
    print(f"  wrote {len(df)} valuation rows")
    _print_failure_summary(failures)


def _print_failure_summary(failures: list):
    total = len(VALUATION_TICKERS) * len(VALUATION_METRICS)
    print("\n" + "=" * 60)
    if not failures:
        print(f"Siblis Research: all {total} ticker/metric pairs fetched OK.")
    else:
        print(f"Siblis Research: {len(failures)} of {total} pairs had no data:")
        for asset_id, metric, reason in failures:
            print(f"  - {asset_id:<20} {metric:<12} {reason}")
    print("=" * 60)


if __name__ == "__main__":
    run()
