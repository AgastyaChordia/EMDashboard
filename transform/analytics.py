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
