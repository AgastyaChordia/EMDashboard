"""
Central definition of everything the dashboard tracks.
Edit this file to add/remove instruments or countries -- nothing else
should need to change when you do.
"""

# --- TLS bootstrap ---------------------------------------------------------
# python.org macOS builds ship without a usable system CA bundle, so urllib
# (used by fredapi) and requests (World Bank) fail with
# CERTIFICATE_VERIFY_FAILED. Every ingest module imports this file before it
# touches the network, so pointing both at certifi's bundle here fixes all of
# them in one place. setdefault() means an explicit override still wins.
import os as _os
try:
    import certifi as _certifi
    _os.environ.setdefault("SSL_CERT_FILE", _certifi.where())
    _os.environ.setdefault("REQUESTS_CA_BUNDLE", _certifi.where())
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 1. GLOBAL EQUITY MARKETS -- top ~20 markets by market cap, tracked via their
#    headline index. Tickers are Yahoo Finance symbols (free, no key needed).
# ---------------------------------------------------------------------------
EQUITY_INDICES = {
    "US_SP500":        "^GSPC",
    "US_NASDAQ":       "^IXIC",
    "CHINA_SSE":       "000001.SS",
    "CHINA_SZSE":      "399001.SZ",
    "JAPAN_NIKKEI":    "^N225",
    "HONGKONG_HSI":    "^HSI",
    "INDIA_NIFTY50":   "^NSEI",
    "UK_FTSE100":      "^FTSE",
    "FRANCE_CAC40":    "^FCHI",
    "GERMANY_DAX":     "^GDAXI",
    "CANADA_TSX":      "^GSPTSE",
    "SWITZERLAND_SMI": "^SSMI",
    "AUSTRALIA_ASX200":"^AXJO",
    "TAIWAN_TWSE":     "^TWII",
    "SKOREA_KOSPI":    "^KS11",
    "BRAZIL_BOVESPA":  "^BVSP",
    "NETHERLANDS_AEX": "^AEX",
    "SPAIN_IBEX35":    "^IBEX",
    "ITALY_FTSEMIB":   "FTSEMIB.MI",
    "INDONESIA_JKSE":  "^JKSE",
    "MEXICO_IPC":      "^MXX",
    "SINGAPORE_STI":   "^STI",
    "SAUDI_TASI":      "^TASI.SR",   # coverage on Yahoo is inconsistent -- verify
    "SOUTHAFRICA_JSE": "^J203.JO",   # JSE All Share
}

# BRICS+ flag, used to slice the dashboard down to your priority list
BRICS_PLUS = {
    "CHINA_SSE", "CHINA_SZSE", "INDIA_NIFTY50", "BRAZIL_BOVESPA",
    "SOUTHAFRICA_JSE", "INDONESIA_JKSE", "SAUDI_TASI",
    # Russia (MOEX) intentionally excluded -- not reliably available on
    # free Western data feeds since 2022. Add a dedicated source if needed.
}

# ---------------------------------------------------------------------------
# 2. CURRENCIES -- Yahoo Finance FX tickers
# ---------------------------------------------------------------------------
CURRENCY_PAIRS = {
    "DXY":     "DX-Y.NYB",
    "USDINR":  "INR=X",
    "EURUSD":  "EURUSD=X",
    "USDJPY":  "JPY=X",
    "GBPUSD":  "GBPUSD=X",
    "USDCNY":  "CNY=X",
    "USDKRW":  "KRW=X",
    "USDTWD":  "TWD=X",
    "AUDUSD":  "AUDUSD=X",
    "USDCHF":  "CHF=X",
}

# ---------------------------------------------------------------------------
# 3. COMMODITIES -- Yahoo Finance futures tickers.
#    Lithium/Nickel don't have reliable free futures data -- proxied via ETFs.
# ---------------------------------------------------------------------------
COMMODITIES = {
    "BRENT_CRUDE":   "BZ=F",
    "WTI_CRUDE":     "CL=F",
    "NATURAL_GAS":   "NG=F",
    "GOLD":          "GC=F",
    "SILVER":        "SI=F",
    "COPPER":        "HG=F",
    "ALUMINIUM_PROXY": "JJU",     # ETF proxy -- LME futures need a paid feed
    "LITHIUM_PROXY": "LIT",       # ETF proxy, not a pure lithium price
    "NICKEL_PROXY":  "JJN",       # ETF proxy
    "WHEAT":         "ZW=F",
    "CORN":          "ZC=F",
    "SOYBEAN":       "ZS=F",
    "COFFEE":        "KC=F",
}

# ---------------------------------------------------------------------------
# 4. FIXED INCOME -- FRED series IDs (free, needs a free API key from
#    https://fred.stlouisfed.org/docs/api/api_key.html)
#    OECD long-term rate series don't cover every EM economy at daily
#    frequency -- gaps are noted. Full EM sovereign curves are a Phase 3+
#    paid-data item (Trading Economics, Refinitiv).
# ---------------------------------------------------------------------------
FRED_YIELDS = {
    "US_2Y":  "DGS2",
    "US_5Y":  "DGS5",
    "US_10Y": "DGS10",
    "US_30Y": "DGS30",
    "GERMANY_10Y": "IRLTLT01DEM156N",   # monthly, OECD via FRED
    "UK_10Y":      "IRLTLT01GBM156N",   # monthly
    "JAPAN_10Y":   "IRLTLT01JPM156N",   # monthly
    "AUSTRALIA_10Y": "IRLTLT01AUM156N", # monthly
    # China, India, Brazil, Korea 10Y: not reliably free at daily frequency.
    # Placeholder -- swap in a paid source or a scraped official central
    # bank series if these matter to you.
}

CREDIT_SPREADS_FRED = {
    "US_HY_SPREAD": "BAMLH0A0HYM2",
    "US_IG_SPREAD": "BAMLC0A0CM",
    "EM_BOND_SPREAD": "BAMLEMCBPIOAS",
}

# ---------------------------------------------------------------------------
# 5. MACRO -- World Bank indicator codes (free, no key). Annual frequency,
#    so this feeds trend context, not weekly moves. PMI has no reliable free
#    global source -- Phase 3 paid-data item (Trading Economics / ISM).
# ---------------------------------------------------------------------------
WORLDBANK_COUNTRIES = {
    "US": "USA", "CHINA": "CHN", "INDIA": "IND", "BRAZIL": "BRA",
    "SOUTHAFRICA": "ZAF", "INDONESIA": "IDN", "JAPAN": "JPN",
    "GERMANY": "DEU", "UK": "GBR", "SAUDI": "SAU", "MEXICO": "MEX",
    "SKOREA": "KOR",
}

WORLDBANK_INDICATORS = {
    "GDP_GROWTH":   "NY.GDP.MKTP.KD.ZG",
    "INFLATION_CPI":"FP.CPI.TOTL.ZG",
    "CURRENT_ACCOUNT_PCT_GDP": "BN.CAB.XOKA.GD.ZS",
    "GOV_DEBT_PCT_GDP": "GC.DOD.TOTL.GD.ZS",
    "UNEMPLOYMENT": "SL.UEM.TOTL.ZS",
}

# ---------------------------------------------------------------------------
# 6. RISK & SENTIMENT -- Yahoo Finance tickers where available
# ---------------------------------------------------------------------------
RISK_SENTIMENT = {
    "VIX": "^VIX",
    "MOVE_PROXY": "^MOVE",  # ticker availability on Yahoo is inconsistent
}

# ---------------------------------------------------------------------------
# Modules deferred to later phases -- listed here so the roadmap lives in
# code, not just in chat. See README.md for the reasoning.
# ---------------------------------------------------------------------------
PHASE_3_MODULES = [
    "valuation (PE, CAPE, EV/EBITDA) -- needs Financial Modeling Prep or similar",
    "earnings & growth (EPS, revisions, ROE) -- needs fundamentals API",
    "sectors -- needs sector index/ETF data + fundamentals",
    "companies -- needs per-company fundamentals API",
]

PHASE_4_MODULES = [
    "ETF & fund flows -- mostly paid (ETF.com, ycharts, EPFR)",
    "economic calendar -- Trading Economics free tier is limited; consider paid",
    "AI daily commentary -- built on top of all other phases, see ai/commentary.py",
]
