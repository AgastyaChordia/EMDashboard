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
from dateutil.relativedelta import relativedelta

from db import read_prices
from config import INDEX_FX_MAP

# Each window is a *calendar* period, matching the convention Google/Yahoo
# Finance use: the anchor is (latest data date - this period), not a fixed
# count of trading rows. relativedelta does true calendar arithmetic (e.g.
# subtracting 1 month from Mar 31 lands on Feb 28/29), unlike a day-count
# approximation. See _anchor_dates for how a weekend/holiday anchor is rolled
# backward to the most recent trading day.
RETURN_WINDOWS = {
    "1M": relativedelta(months=1),
    "3M": relativedelta(months=3),
    "6M": relativedelta(months=6),
    "1Y": relativedelta(years=1),
    "3Y": relativedelta(years=3),
    "5Y": relativedelta(years=5),
    "10Y": relativedelta(years=10),
}


def _pivot_close(module: str) -> pd.DataFrame:
    df = read_prices(module=module)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot(index="date", columns="asset_id", values="close").sort_index()


def _anchor_dates(s: pd.Series, offset: relativedelta):
    """Calendar-anchored (end_date, start_date) for one asset's close series,
    or (None, None) if history doesn't reach the window.

    - end_date   = the asset's own latest available data date.
    - start_date = the most recent trading day at or before
      (end_date - offset). If the anchor lands on a weekend/holiday/gap we roll
      *backward* only (never forward -- forward would shorten the window).
    - If no data exists at or before the anchor, returns (None, None) so the
      caller yields NaN rather than falling back to the earliest row.
    """
    s = s.dropna()
    if s.empty:
        return None, None
    end_date = s.index[-1]
    anchor = end_date - offset
    prior = s.loc[:anchor]          # inclusive of anchor; backward fill only
    if prior.empty:
        return None, None
    return end_date, prior.index[-1]


def period_returns(module: str) -> pd.DataFrame:
    """% return over each calendar window in RETURN_WINDOWS, per asset.

    Anchoring is per-asset and calendar-based (see _anchor_dates): the endpoint
    is each asset's latest close, the start is the most recent trading day at or
    before end-minus-window. Assets without enough history for a window get NaN
    for that column."""
    px = _pivot_close(module)
    if px.empty:
        return pd.DataFrame()
    out = {}
    for label, offset in RETURN_WINDOWS.items():
        col = {}
        for asset_id in px.columns:
            s = px[asset_id]
            end_d, start_d = _anchor_dates(s, offset)
            col[asset_id] = (np.nan if end_d is None
                             else (s.loc[end_d] / s.loc[start_d] - 1) * 100)
        out[label] = pd.Series(col)
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
    Values are in percent, matching period_returns().

    Crucially, the FX leg is evaluated on the *same* (end_date, start_date)
    anchors as the local return for that asset+window -- the factor series is
    aligned to the equity calendar, then indexed by those exact dates -- so the
    USD numbers can't drift from the local ones."""
    px = _pivot_close(module)
    if px.empty:
        return pd.DataFrame()
    factor = _usd_per_local_factor(px.index)
    if factor.empty:
        return pd.DataFrame()
    out = {}
    for label, offset in RETURN_WINDOWS.items():
        col = {}
        for asset_id in px.columns:
            if asset_id not in factor.columns:
                col[asset_id] = np.nan          # no FX mapping -> blank
                continue
            s = px[asset_id]
            end_d, start_d = _anchor_dates(s, offset)
            if end_d is None:
                col[asset_id] = np.nan          # not enough history -> blank
                continue
            local = s.loc[end_d] / s.loc[start_d] - 1
            f = factor[asset_id]
            fx_ret = f.loc[end_d] / f.loc[start_d] - 1   # same anchor dates
            col[asset_id] = ((1 + local) * (1 + fx_ret) - 1) * 100
        out[label] = pd.Series(col)
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
