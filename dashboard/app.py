"""
Run with: streamlit run dashboard/app.py

This reads only from DuckDB -- it never calls external APIs itself, so it
stays fast and works offline once ingest/ has populated the database.

Visual layer: dark "terminal" theme (see .streamlit/config.toml), Plotly
charts on a plotly_dark template, KPI cards and a top ticker strip. Raw
tables are tucked behind "Show detailed table" expanders so the default
view is charts + cards, not spreadsheets.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (EQUITY_INDICES, CURRENCY_PAIRS, COMMODITIES, RISK_SENTIMENT,
                    BRICS_PLUS, PHASE_3_MODULES, PHASE_4_MODULES)
from db import (read_prices, get_connection, init_schema, has_price_data,
                get_secret)
from transform.analytics import (period_returns, volatility, correlation_matrix,
                                 drawdown)

# --------------------------------------------------------------------------
# Palette -- kept in one place so every chart/card stays on-theme.
# --------------------------------------------------------------------------
VIOLET   = "#7c6df2"
TEAL     = "#2dd4bf"   # positive returns
CORAL    = "#fb7185"   # negative returns
GREEN    = "#22c55e"   # ticker strip up
RED      = "#ef4444"   # ticker strip down
CARD_BG  = "#1a1d29"
CARD_BRD = "#2a2e3d"
MUTED    = "#8b8fa3"
TEXT     = "#e6e8f0"
DASH     = "–"    # en dash, used for missing values

st.set_page_config(page_title="Global Markets Terminal", layout="wide",
                   page_icon="\U0001F4C8")

# A little CSS to tighten the terminal feel.
st.markdown("""
<style>
  .block-container {padding-top: 2rem;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  .tick-strip {display:flex; gap:26px; overflow-x:auto; padding:10px 14px;
      background:#12141d; border:1px solid #2a2e3d; border-radius:10px;
      font-variant-numeric:tabular-nums; white-space:nowrap;}
  .tick-item {display:flex; flex-direction:column; line-height:1.25;}
  .tick-name {font-size:11px; color:#8b8fa3; letter-spacing:.5px;}
  .tick-px   {font-size:15px; font-weight:600; color:#e6e8f0;}
  /* KPI cards live in a responsive grid: 4-up on desktop, wrapping down to
     2-up / 1-up on narrow screens without any server-side width detection. */
  .kpi-grid {display:grid; gap:12px;
      grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));}
  .kpi {background:#1a1d29; border:1px solid #2a2e3d; border-radius:12px;
      padding:14px 16px; height:100%;}
  .kpi-label {font-size:11px; color:#8b8fa3; text-transform:uppercase;
      letter-spacing:.6px;}
  .kpi-val {font-size:26px; font-weight:650; color:#e6e8f0; margin-top:2px;}
  .badge {display:inline-block; margin-top:8px; padding:2px 9px; border-radius:20px;
      font-size:12px; font-weight:600;}
  /* Mobile: stack Streamlit's side-by-side st.columns full width, and give
     charts/text a little more room by trimming page padding. */
  @media (max-width: 640px) {
    .block-container {padding-left:.7rem; padding-right:.7rem; padding-top:1rem;}
    .kpi-val {font-size:22px;}
    .tick-strip {gap:18px;}
    [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex:1 1 100% !important; width:100% !important; min-width:100% !important;}
  }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Formatting + chart helpers
# --------------------------------------------------------------------------
def fmt(v, suffix="", pct=False, decimals=2):
    """Render a number, turning NaN/None into an en dash so the UI never
    shows the literal word 'None' or a blank cell."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return DASH
    sign = "+" if (pct and v > 0) else ""
    return f"{sign}{v:,.{decimals}f}{'%' if pct else ''}{suffix}"


def style_table(df: pd.DataFrame):
    """Format a *numeric* dataframe for display: show NaN as an en dash and
    round floats, WITHOUT mutating the underlying data. Returns a pandas
    Styler so the columns stay numeric -- writing the '–' string into the
    data itself produced mixed str/float columns that pyarrow refused to
    serialize (ArrowInvalid: "Could not convert '-' ...")."""
    return df.style.format(na_rep=DASH, precision=2, thousands=",")


def kpi_row(items):
    """items: list of (label, value_str, delta_pct_or_None). Renders the cards
    in a single responsive CSS grid (see .kpi-grid) so they wrap gracefully on
    narrow screens instead of squishing into fixed st.columns."""
    cards = []
    for label, value, delta in items:
        if delta is None:
            badge = ""
        else:
            up = delta >= 0
            color = TEAL if up else CORAL
            bg = "rgba(45,212,191,.14)" if up else "rgba(251,113,133,.14)"
            badge = (f"<span class='badge' style='background:{bg};color:{color}'>"
                     f"{'+' if up else ''}{delta:.2f}%</span>")
        cards.append(
            f"<div class='kpi'><div class='kpi-label'>{label}</div>"
            f"<div class='kpi-val'>{value}</div>{badge}</div>")
    st.markdown(f"<div class='kpi-grid'>{''.join(cards)}</div>",
                unsafe_allow_html=True)


def returns_bar(series: pd.Series, title: str):
    """Horizontal bar chart of returns, teal positive / coral negative."""
    s = series.dropna().sort_values()
    if s.empty:
        st.info("No data for this window yet.")
        return
    colors = [TEAL if v >= 0 else CORAL for v in s.values]
    fig = go.Figure(go.Bar(
        x=s.values, y=s.index, orientation="h",
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in s.values], textposition="auto",
        hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
    fig.update_layout(
        template="plotly_dark", title=title, height=max(320, 26 * len(s)),
        margin=dict(l=10, r=10, t=48, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="% return", yaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)


def area_chart(series: pd.Series, title: str, color: str = VIOLET, unit="%"):
    """Time series as an area chart with a subtle gradient fill."""
    s = series.dropna()
    if s.empty:
        st.info("No data yet.")
        return
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fig = go.Figure(go.Scatter(
        x=s.index, y=s.values, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=f"rgba({r},{g},{b},0.16)",
        hovertemplate=f"%{{x|%Y-%m-%d}}: %{{y:.2f}}{unit}<extra></extra>"))
    fig.update_layout(
        template="plotly_dark", title=title, height=340,
        margin=dict(l=10, r=10, t=48, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)


@st.cache_data(ttl=300)
def latest_changes(module: str) -> pd.DataFrame:
    """Latest close + 1-day % change per asset in a module. Uses the last
    *valid* close per asset so a trailing NaN (holiday, partial feed) never
    surfaces as 'nan' in the ticker strip."""
    df = read_prices(module=module)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    px = df.pivot(index="date", columns="asset_id", values="close").sort_index()
    out = {}
    for col in px.columns:
        s = px[col].dropna()
        if s.empty:
            continue
        last = s.iloc[-1]
        prev = s.iloc[-2] if len(s) > 1 else last
        out[col] = {"price": last, "chg": (last / prev - 1) * 100}
    return pd.DataFrame(out).T


def ticker_strip(asset_ids):
    """Horizontal stock-ticker strip: name, price, colored % change."""
    changes = latest_changes("equities")
    if changes.empty:
        return
    items = []
    for aid in asset_ids:
        if aid not in changes.index:
            continue
        price, chg = changes.loc[aid, "price"], changes.loc[aid, "chg"]
        color = GREEN if chg >= 0 else RED
        arrow = "▲" if chg >= 0 else "▼"
        items.append(
            f"<div class='tick-item'><span class='tick-name'>{aid}</span>"
            f"<span class='tick-px'>{price:,.2f} "
            f"<span style='color:{color};font-size:13px'>{arrow} "
            f"{chg:+.2f}%</span></span></div>")
    if items:
        st.markdown(f"<div class='tick-strip'>{''.join(items)}</div>",
                    unsafe_allow_html=True)


def top_movers_kpis(returns: pd.DataFrame, window="1M", n=4):
    """KPI cards for the biggest movers over `window`."""
    if returns.empty or window not in returns.columns:
        return
    s = returns[window].dropna().sort_values(ascending=False)
    if s.empty:
        return
    top = list(s.head(n).items())
    items = [(aid, fmt(val, pct=True), val) for aid, val in top]
    st.caption(f"Top movers · {window}")
    kpi_row(items)


# --------------------------------------------------------------------------
# Section renderers
# --------------------------------------------------------------------------
def render_equities():
    st.subheader("Global equity indices")
    only_brics = st.toggle("BRICS+ only", value=False)
    returns = period_returns("equities")
    if returns.empty:
        st.info("No data yet -- run `python ingest/market_data.py` first.")
        return
    if only_brics:
        returns = returns[returns.index.isin(BRICS_PLUS)]

    windows = [w for w in ["1M", "3M", "6M", "1Y", "3Y", "5Y"] if w in returns.columns]
    window = st.radio("Return window", windows,
                      index=min(1, len(windows) - 1), horizontal=True)
    top_movers_kpis(returns, window)
    returns_bar(returns[window], f"Equity returns — {window}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Volatility** (21D annualized)")
        vol = volatility("equities")
        if only_brics:
            vol = vol[vol.index.isin(BRICS_PLUS)]
        returns_bar(vol["volatility_pct"], "Realized volatility %")
    with c2:
        st.markdown("**Drawdown**")
        options = list(returns.index)
        asset = st.selectbox("Index", options)
        area_chart(drawdown("equities", asset), f"{asset} drawdown", color=CORAL)

    with st.expander("Show detailed table"):
        st.dataframe(style_table(returns), use_container_width=True)
        st.markdown("**Correlation matrix (1Y daily returns)**")
        st.dataframe(style_table(correlation_matrix("equities")),
                     use_container_width=True)


def render_currencies():
    st.subheader("Currency pairs")
    returns = period_returns("currencies")
    if returns.empty:
        st.info("No data yet -- run `python ingest/market_data.py` first.")
        return
    windows = [w for w in ["1M", "3M", "6M", "1Y"] if w in returns.columns]
    window = st.radio("Return window", windows, index=0, horizontal=True)
    top_movers_kpis(returns, window)
    returns_bar(returns[window], f"Currency moves — {window}")
    with st.expander("Show detailed table"):
        st.dataframe(style_table(returns), use_container_width=True)
        st.markdown("**Volatility** (21D annualized, %)")
        st.dataframe(style_table(volatility("currencies")),
                     use_container_width=True)


def render_commodities():
    st.subheader("Commodities")
    returns = period_returns("commodities")
    if returns.empty:
        st.info("No data yet -- run `python ingest/market_data.py` first.")
        return
    windows = [w for w in ["1M", "3M", "6M", "1Y"] if w in returns.columns]
    window = st.radio("Return window", windows, index=0, horizontal=True)
    top_movers_kpis(returns, window)
    returns_bar(returns[window], f"Commodity returns — {window}")
    st.caption("Aluminium/Lithium/Nickel are ETF proxies, not pure futures "
               "prices -- see config.py")
    with st.expander("Show detailed table"):
        st.dataframe(style_table(returns), use_container_width=True)


def render_fixed_income():
    st.subheader("Sovereign yields & credit spreads")
    df = read_prices(module="fixed_income_yields")
    if df.empty:
        st.info("No data yet -- set FRED_API_KEY and run "
                "`python ingest/fixed_income.py`.")
    else:
        latest = (df.sort_values("date").groupby("asset_id").tail(1)
                  .set_index("asset_id")["close"])
        items = [(aid, fmt(val, suffix="%"), None) for aid, val in latest.items()]
        for i in range(0, len(items), 4):
            kpi_row(items[i:i + 4])
        returns_bar(latest, "Latest yield by tenor (%)")
        with st.expander("Show detailed table"):
            tbl = (df.sort_values("date").groupby("asset_id").tail(1)
                   [["asset_id", "date", "close"]]
                   .rename(columns={"close": "yield_%"}))
            st.dataframe(style_table(tbl), use_container_width=True)

    spreads = read_prices(module="credit_spreads")
    if not spreads.empty:
        st.markdown("**Credit spreads (bps / %)**")
        latest = (spreads.sort_values("date").groupby("asset_id").tail(1)
                  .set_index("asset_id")["close"])
        kpi_row([(aid, fmt(val), None) for aid, val in latest.items()])
    st.caption("China/India/Brazil/Korea 10Y not included yet -- free daily "
               "series aren't reliably available. See config.py.")


def render_macro():
    st.subheader("Macro indicators (World Bank, annual)")
    con = get_connection()
    macro = con.execute(
        "SELECT * FROM macro_indicators ORDER BY country, indicator, date DESC").df()
    con.close()
    if macro.empty:
        st.info("No data yet -- run `python ingest/macro.py` first.")
        return
    latest = macro.groupby(["country", "indicator"]).first().reset_index()
    pivot = latest.pivot(index="country", columns="indicator", values="value")
    indicator = st.selectbox("Indicator", list(pivot.columns))
    returns_bar(pivot[indicator], f"{indicator} by country (latest annual)")
    with st.expander("Show detailed table"):
        st.dataframe(style_table(pivot), use_container_width=True)


def render_risk():
    st.subheader("Risk & sentiment")
    changes = latest_changes("risk_sentiment")
    if not changes.empty:
        items = [(aid, fmt(row["price"]), row["chg"])
                 for aid, row in changes.iterrows()]
        kpi_row(items)
    returns = period_returns("risk_sentiment")
    if returns.empty:
        st.info("No data yet -- run `python ingest/market_data.py` first.")
        return
    windows = [w for w in ["1M", "3M", "6M", "1Y"] if w in returns.columns]
    window = st.radio("Return window", windows, index=0, horizontal=True)
    returns_bar(returns[window], f"Risk index moves — {window}")
    with st.expander("Show detailed table"):
        st.dataframe(style_table(returns), use_container_width=True)


def render_briefing():
    st.subheader("AI weekly briefing")
    con = get_connection()
    latest = con.execute(
        "SELECT * FROM commentary ORDER BY generated_at DESC LIMIT 1").df()
    con.close()
    if latest.empty:
        st.info("No briefing yet -- set ANTHROPIC_API_KEY and run "
                "`python ai/commentary.py` after the ingest scripts.")
        return
    row = latest.iloc[0]
    st.caption(f"Generated {row['generated_at']}")
    st.markdown(f"<div class='kpi' style='padding:22px 26px;line-height:1.6'>"
                f"{row['body']}</div>", unsafe_allow_html=True)


def render_roadmap():
    st.subheader("Roadmap — not built yet")
    st.markdown("**Phase 3**")
    for item in PHASE_3_MODULES:
        st.markdown(f"- {item}")
    st.markdown("**Phase 4**")
    for item in PHASE_4_MODULES:
        st.markdown(f"- {item}")


# --------------------------------------------------------------------------
# First-run ingestion: on a fresh deploy (e.g. Streamlit Cloud) the DuckDB
# file isn't in git, so the DB is empty. Let the user populate it in-app.
# --------------------------------------------------------------------------
def run_full_ingestion():
    """Run the full pipeline in-app with a live progress indicator, then
    clear cached reads and rerun so the fresh data shows immediately. Keys
    come from get_secret() -> env var or st.secrets."""
    # Imported lazily so a normal page load doesn't pay yfinance's import cost.
    from ingest import market_data, fixed_income, macro
    with st.status("Fetching market data — this takes a couple of minutes…",
                   expanded=True) as status:
        st.write("① Equities, currencies, commodities, risk (Yahoo Finance)…")
        market_data.run()
        st.write("② Sovereign yields & credit spreads (FRED)…")
        fixed_income.run()
        st.write("③ Macro indicators (World Bank)…")
        macro.run()
        st.write("④ Generating AI weekly briefing…")
        try:
            from ai.commentary import generate_weekly_commentary
            generate_weekly_commentary()
        except Exception as e:
            st.write(f"   AI briefing skipped: {e}")
        status.update(label="Data ready ✓", state="complete")
    # DuckDB now holds the data (persists across reruns/opens on the same
    # container). Clear the @st.cache_data read caches so charts pick it up;
    # we only ever refetch from the network when a button is clicked again.
    st.cache_data.clear()
    st.rerun()


def render_first_run():
    st.info("**No data yet — click below to fetch it.** This deploy started "
            "with an empty database (the DuckDB file isn't committed to git). "
            "The button pulls live data from Yahoo Finance, FRED and the "
            "World Bank, and generates the AI briefing.")
    missing = [k for k in ("FRED_API_KEY", "ANTHROPIC_API_KEY")
               if not get_secret(k)]
    if missing:
        st.warning(
            "Missing secret(s): **" + ", ".join(missing) + "**. Add them in "
            "Streamlit Cloud → Settings → Secrets. FRED powers the yields tab "
            "and ANTHROPIC the AI briefing; equities/FX/commodities/macro will "
            "still load without them.")
    if st.button("⬇  Fetch market data now", type="primary"):
        run_full_ingestion()


# --------------------------------------------------------------------------
# Layout: sidebar nav + ticker strip + selected section
# --------------------------------------------------------------------------
SECTIONS = {
    "\U0001F4C8  Equities":        render_equities,
    "\U0001F4B1  Currencies":      render_currencies,
    "\U0001F6E2️  Commodities": render_commodities,
    "\U0001F3E6  Fixed income":    render_fixed_income,
    "\U0001F30D  Macro":           render_macro,
    "⚠️  Risk & sentiment": render_risk,
    "\U0001F916  AI briefing":     render_briefing,
    "\U0001F5FA️  Roadmap":    render_roadmap,
}

# Make sure the tables exist before any read -- on a fresh deploy they won't.
init_schema()
data_ready = has_price_data()

with st.sidebar:
    st.markdown("### \U0001F4CA Global Markets Terminal")
    st.caption("Emerging & global markets · BRICS+ focus")
    choice = st.radio("Navigate", list(SECTIONS.keys()), label_visibility="collapsed")
    st.divider()
    st.caption("Data: Yahoo Finance · FRED · World Bank")
    if data_ready:
        # Persistent refetch control -- data is otherwise cached (the DuckDB
        # file), so the network is only hit when this is clicked.
        if st.button("↻  Refresh data"):
            run_full_ingestion()

st.title("Global & emerging markets")

if not data_ready:
    render_first_run()
    st.stop()

ticker_strip(["US_SP500", "CHINA_SSE", "JAPAN_NIKKEI", "INDIA_NIFTY50",
              "UK_FTSE100", "BRAZIL_BOVESPA"])
st.write("")

SECTIONS[choice]()
