"""
Turns raw price history into the derived metrics the dashboard shows:
period returns, rolling returns, drawdown, volatility, correlation matrix.
Nothing here hits the network -- it only reads what ingest/ already wrote
to DuckDB, so it's cheap to re-run as often as you like.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

from db import read_prices
from config import INDEX_FX_MAP

RETURN_WINDOWS = {
    "1M": 21, "3M": 63, "6M": 126, "1Y": 252,
    "3Y": 756, "5Y": 1260, "10Y": 2520,
    # ingest/market_data.py now pulls period="max", so these long windows have
    # the history they need. Any asset whose series is shorter than a given
    # window simply comes back blank for that column (shown as "-" in the UI).
}


def _pivot_close(module: str) -> pd.DataFrame:
    df = read_prices(module=module)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot(index="date", columns="asset_id", values="close").sort_index()


def period_returns(module: str) -> pd.DataFrame:
    """% return over each window in RETURN_WINDOWS, for every asset in the module."""
    px = _pivot_close(module)
    if px.empty:
        return pd.DataFrame()
    out = {}
    latest = px.iloc[-1]
    for label, days in RETURN_WINDOWS.items():
        if len(px) > days:
            past = px.iloc[-days - 1]
            out[label] = (latest / past - 1) * 100
    return pd.DataFrame(out)


def _usd_per_local_factor(px_index: pd.Index) -> pd.DataFrame:
    """One column per equity index giving the USD-per-unit-of-local-currency
    factor, aligned to the equity trading calendar `px_index`.

    A rising factor == local currency strengthening vs USD == tailwind for a
    USD-based investor. For USD_PER_FOREIGN pairs the quoted pair already *is*
    that factor; for FOREIGN_PER_USD pairs it's inverted (1/pair); USD-priced
    indices get a constant 1.0. Indices with no mapped/available pair are
    omitted, so downstream returns come back NaN for them (never fabricated).
    DXY is never referenced -- it isn't a bilateral pair in INDEX_FX_MAP.
    """
    fx = _pivot_close("currencies")
    factors = {}
    for asset_id, (pair, quote) in INDEX_FX_MAP.items():
        if quote == "USD":
            factors[asset_id] = pd.Series(1.0, index=px_index)
            continue
        if fx.empty or pair not in fx.columns:
            continue                      # no FX data for this pair -> blank
        # Align FX close onto the equity calendar; forward-fill only bridges
        # holiday/calendar gaps. Dates before the FX series starts stay NaN,
        # so a window with missing FX history yields a NaN (blank) USD return.
        rate = fx[pair].reindex(px_index).ffill()
        factors[asset_id] = rate if quote == "USD_PER_FOREIGN" else 1.0 / rate
    return pd.DataFrame(factors, index=px_index)


def period_returns_usd(module: str = "equities") -> pd.DataFrame:
    """USD-adjusted counterpart to period_returns(): for each window, combines
    the local-currency index return with the FX return over the *same* two
    endpoint dates, multiplicatively:

        USD_return = (1 + local_return) * (1 + fx_return) - 1

    where fx_return already carries the correct sign per INDEX_FX_MAP. Indices
    without a clean FX match (or with missing FX for the window) come back NaN.
    Values are in percent, matching period_returns()."""
    px = _pivot_close(module)
    if px.empty:
        return pd.DataFrame()
    factor = _usd_per_local_factor(px.index)
    if factor.empty:
        return pd.DataFrame()
    out = {}
    for label, days in RETURN_WINDOWS.items():
        if len(px) <= days:
            continue
        local = px.iloc[-1] / px.iloc[-days - 1] - 1
        fx_ret = factor.iloc[-1] / factor.iloc[-days - 1] - 1
        # Series align on asset_id; indices absent from `factor` -> NaN, which
        # propagates so their USD cell stays blank rather than mirroring local.
        out[label] = ((1 + local) * (1 + fx_ret) - 1) * 100
    return pd.DataFrame(out)


def rolling_returns(module: str, asset_id: str, window_days: int = 252) -> pd.Series:
    px = _pivot_close(module)
    if px.empty or asset_id not in px.columns:
        return pd.Series(dtype=float)
    return px[asset_id].pct_change(window_days) * 100


def drawdown(module: str, asset_id: str) -> pd.Series:
    px = _pivot_close(module)
    if px.empty or asset_id not in px.columns:
        return pd.Series(dtype=float)
    s = px[asset_id].dropna()
    running_max = s.cummax()
    return (s / running_max - 1) * 100


def volatility(module: str, window_days: int = 21, annualize: bool = True) -> pd.DataFrame:
    """Realized volatility (%) over a rolling window, latest value per asset."""
    px = _pivot_close(module)
    if px.empty:
        return pd.DataFrame()
    daily_ret = px.pct_change()
    vol = daily_ret.rolling(window_days).std()
    if annualize:
        vol = vol * np.sqrt(252)
    return (vol.iloc[-1] * 100).rename("volatility_pct").to_frame()


def correlation_matrix(module: str, window_days: int = 252) -> pd.DataFrame:
    px = _pivot_close(module)
    if px.empty:
        return pd.DataFrame()
    daily_ret = px.pct_change().tail(window_days)
    return daily_ret.corr()


if __name__ == "__main__":
    print("Equity period returns:")
    print(period_returns("equities"))
    print("\nEquity correlation matrix (1Y):")
    print(correlation_matrix("equities"))
