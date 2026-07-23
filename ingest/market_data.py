"""
Pulls equities, currencies, commodities, and risk/sentiment tickers --
everything on Yahoo Finance, via yfinance. No API key needed.

Run this from an environment with real internet access (your machine, a
cloud VM, or a scheduled GitHub Action) -- it will not work inside a
network-restricted sandbox.
"""
import sys
import time
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from config import EQUITY_INDICES, CURRENCY_PAIRS, COMMODITIES, RISK_SENTIMENT
from db import upsert_prices, init_schema, write_ticker_batch

# Retry policy for transient Yahoo failures (rate-limit / timeout): 3 attempts
# with exponential backoff (2s, 4s) between them.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0

# Every yfinance ticker group, in fetch order. One place so the total count and
# the iteration used for progress/resume stay in sync.
TICKER_GROUPS = [
    (EQUITY_INDICES, "equities"),
    (CURRENCY_PAIRS, "currencies"),
    (COMMODITIES, "commodities"),
    (RISK_SENTIMENT, "risk_sentiment"),
]


def total_ticker_count() -> int:
    return sum(len(m) for m, _ in TICKER_GROUPS)


def iter_all_tickers():
    """(asset_id, ticker, module) for every yfinance ticker, in fetch order."""
    for ticker_map, module in TICKER_GROUPS:
        for asset_id, ticker in ticker_map.items():
            yield asset_id, ticker, module


def _fetch_one(ticker: str, period: str):
    """Fetch a single ticker's history with retry + exponential backoff. Returns
    the (possibly empty) history frame; re-raises the last error only after all
    attempts fail, so one transient blip doesn't abort or half-write a ticker."""
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return yf.Ticker(ticker).history(period=period)
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
    raise last_err


def _hist_to_rows(hist: pd.DataFrame, asset_id: str, module: str) -> pd.DataFrame:
    hist = hist.reset_index()
    rows = [{
        "asset_id": asset_id,
        "module": module,
        "date": r["Date"].date(),
        "open": r.get("Open"),
        "high": r.get("High"),
        "low": r.get("Low"),
        "close": r.get("Close"),
        "volume": r.get("Volume", 0),
    } for _, r in hist.iterrows()]
    return pd.DataFrame(rows)


def run_resumable(period: str = "max", run_id=None, skip=None, on_progress=None):
    """Fetch every yfinance ticker one at a time with per-ticker retry.

    - run_id set  -> each ticker's rows and its 'success'/'failed' marker are
                     written together in one transaction (db.write_ticker_batch),
                     making the run resumable and its progress inspectable.
      run_id None -> plain upserts, no progress log (CLI / one-shot use).
    - skip        -> set of asset_ids already fetched in this run; skipped.
    - on_progress -> callback(done, total, asset_id, status) after each ticker,
                     with status one of 'success' | 'failed' | 'skipped'.

    Returns (successes, failures) where failures are (asset_id, ticker, reason).
    """
    skip = skip or set()
    total = total_ticker_count()
    done = 0
    successes, failures = [], []
    for asset_id, ticker, module in iter_all_tickers():
        if asset_id in skip:
            done += 1
            successes.append(asset_id)
            if on_progress:
                on_progress(done, total, asset_id, "skipped")
            continue
        try:
            hist = _fetch_one(ticker, period)
            if hist is None or hist.empty:
                reason = "no data returned"
                if run_id:
                    write_ticker_batch(None, run_id, asset_id, module, ticker,
                                       "failed", reason)
                failures.append((asset_id, ticker, reason))
                status = "failed"
            else:
                price_df = _hist_to_rows(hist, asset_id, module)
                if run_id:
                    write_ticker_batch(price_df, run_id, asset_id, module,
                                       ticker, "success", None)
                else:
                    upsert_prices(price_df)
                successes.append(asset_id)
                status = "success"
        except Exception as e:
            if run_id:
                try:
                    write_ticker_batch(None, run_id, asset_id, module, ticker,
                                       "failed", str(e))
                except Exception:
                    pass
            failures.append((asset_id, ticker, str(e)))
            status = "failed"
        done += 1
        if on_progress:
            on_progress(done, total, asset_id, status)
    return successes, failures


def run(period: str = "max"):
    """Fetch everything and write to DuckDB. Safe to re-run -- upserts by (asset_id, date).

    Defaults to period="max" so the long return windows (5Y/10Y/...) in
    transform/analytics.py actually have the history they need. Pass a shorter
    period (e.g. "2y") if you just want a quick refresh.
    """
    init_schema()

    def _cli(done, total, asset_id, status):
        print(f"  [{done}/{total}] {asset_id}: {status}")

    _, failures = run_resumable(period=period, on_progress=_cli)
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
