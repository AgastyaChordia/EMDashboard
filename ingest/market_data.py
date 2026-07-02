"""
Pulls equities, currencies, commodities, and risk/sentiment tickers --
everything on Yahoo Finance, via yfinance. No API key needed.

Run this from an environment with real internet access (your machine, a
cloud VM, or a scheduled GitHub Action) -- it will not work inside a
network-restricted sandbox.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from config import EQUITY_INDICES, CURRENCY_PAIRS, COMMODITIES, RISK_SENTIMENT
from db import upsert_prices, init_schema


def fetch_tickers(ticker_map: dict, module: str, period: str = "max",
                  failures: list = None) -> pd.DataFrame:
    """
    ticker_map: {asset_id: yahoo_ticker}
    Returns a tidy dataframe ready for db.upsert_prices.
    Any ticker that returns nothing or raises is appended to `failures` as
    (asset_id, ticker, reason) so run() can print one summary at the end.
    """
    rows = []
    for asset_id, ticker in ticker_map.items():
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist.empty:
                print(f"  [warn] no data returned for {asset_id} ({ticker})")
                if failures is not None:
                    failures.append((asset_id, ticker, "no data returned"))
                continue
            hist = hist.reset_index()
            for _, r in hist.iterrows():
                rows.append({
                    "asset_id": asset_id,
                    "module": module,
                    "date": r["Date"].date(),
                    "open": r.get("Open"),
                    "high": r.get("High"),
                    "low": r.get("Low"),
                    "close": r.get("Close"),
                    "volume": r.get("Volume", 0),
                })
        except Exception as e:
            print(f"  [error] {asset_id} ({ticker}): {e}")
            if failures is not None:
                failures.append((asset_id, ticker, str(e)))
    return pd.DataFrame(rows)


def run(period: str = "max"):
    """Fetch everything and write to DuckDB. Safe to re-run -- upserts by (asset_id, date).

    Defaults to period="max" so the long return windows (5Y/10Y/...) in
    transform/analytics.py actually have the history they need. Pass a shorter
    period (e.g. "2y") if you just want a quick refresh.
    """
    init_schema()
    failures = []

    print("Fetching equity indices...")
    df = fetch_tickers(EQUITY_INDICES, "equities", period, failures)
    upsert_prices(df)
    print(f"  wrote {len(df)} rows")

    print("Fetching currency pairs...")
    df = fetch_tickers(CURRENCY_PAIRS, "currencies", period, failures)
    upsert_prices(df)
    print(f"  wrote {len(df)} rows")

    print("Fetching commodities...")
    df = fetch_tickers(COMMODITIES, "commodities", period, failures)
    upsert_prices(df)
    print(f"  wrote {len(df)} rows")

    print("Fetching risk/sentiment tickers...")
    df = fetch_tickers(RISK_SENTIMENT, "risk_sentiment", period, failures)
    upsert_prices(df)
    print(f"  wrote {len(df)} rows")

    _print_failure_summary(failures)


def _print_failure_summary(failures: list):
    """Print a clear end-of-run list of exactly which tickers failed and why."""
    total = len(EQUITY_INDICES) + len(CURRENCY_PAIRS) + len(COMMODITIES) + len(RISK_SENTIMENT)
    print("\n" + "=" * 60)
    if not failures:
        print(f"Yahoo Finance: all {total} tickers fetched OK.")
    else:
        print(f"Yahoo Finance: {len(failures)} of {total} tickers FAILED:")
        for asset_id, ticker, reason in failures:
            print(f"  - {asset_id:<20} {ticker:<14} {reason}")
    print("=" * 60)


if __name__ == "__main__":
    run()
