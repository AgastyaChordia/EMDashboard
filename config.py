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
    "INDIA_SENSEX":    "^BSESN",     # BSE Sensex -- verified on Yahoo
    "INDIA_NIFTYBANK": "^NSEBANK",   # Nifty Bank -- verified on Yahoo
    "INDIA_NIFTY_MIDCAP50": "^NSEMDCP50",  # Nifty Midcap 50 -- verified on Yahoo
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

# Indian indices, grouped so the dashboard can filter to them the same way
# it filters BRICS+. All four are verified to return data from Yahoo Finance.
INDIA_INDICES = {
    "INDIA_NIFTY50", "INDIA_SENSEX", "INDIA_NIFTYBANK", "INDIA_NIFTY_MIDCAP50",
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
# 2b. EQUITY INDEX -> FX PAIR, for USD-adjusting local-currency index returns.
#     Maps each index (by its home country's currency) to the matching
#     bilateral pair in CURRENCY_PAIRS, plus how that pair is *quoted*, which
#     decides the sign of the FX effect when combined with the local return:
#
#       "USD_PER_FOREIGN"  pair value = USD per 1 unit of local currency
#                          (EURUSD, GBPUSD, AUDUSD). A rising pair means the
#                          local currency strengthened vs USD -> tailwind, so
#                          the pair's own return combines directly.
#       "FOREIGN_PER_USD"  pair value = local-currency units per 1 USD
#                          (USDINR/USDJPY/USDCNY/USDCHF/USDKRW/USDTWD). This is
#                          inverted: a rising pair means the local currency
#                          *weakened*, so we invert (1/pair) before combining.
#       "USD"              index is already priced in USD (US) -> USD return
#                          equals local return, no FX conversion.
#
#     DXY is the dollar index, not a bilateral pair -- deliberately never used
#     to convert a single index. Indices whose currency has no matching pair
#     here (HKD, CAD, BRL, IDR, MXN, SGD, SAR, ZAR) are omitted entirely: their
#     USD return is left blank rather than estimated. Never fabricate a rate.
# ---------------------------------------------------------------------------
INDEX_FX_MAP = {
    "US_SP500":              ("USD",    "USD"),
    "US_NASDAQ":             ("USD",    "USD"),
    "CHINA_SSE":             ("USDCNY", "FOREIGN_PER_USD"),
    "CHINA_SZSE":            ("USDCNY", "FOREIGN_PER_USD"),
    "JAPAN_NIKKEI":          ("USDJPY", "FOREIGN_PER_USD"),
    "INDIA_NIFTY50":         ("USDINR", "FOREIGN_PER_USD"),
    "INDIA_SENSEX":          ("USDINR", "FOREIGN_PER_USD"),
    "INDIA_NIFTYBANK":       ("USDINR", "FOREIGN_PER_USD"),
    "INDIA_NIFTY_MIDCAP50":  ("USDINR", "FOREIGN_PER_USD"),
    "UK_FTSE100":            ("GBPUSD", "USD_PER_FOREIGN"),
    "FRANCE_CAC40":          ("EURUSD", "USD_PER_FOREIGN"),
    "GERMANY_DAX":           ("EURUSD", "USD_PER_FOREIGN"),
    "SWITZERLAND_SMI":       ("USDCHF", "FOREIGN_PER_USD"),
    "AUSTRALIA_ASX200":      ("AUDUSD", "USD_PER_FOREIGN"),
    "TAIWAN_TWSE":           ("USDTWD", "FOREIGN_PER_USD"),
    "SKOREA_KOSPI":          ("USDKRW", "FOREIGN_PER_USD"),
    "NETHERLANDS_AEX":       ("EURUSD", "USD_PER_FOREIGN"),
    "SPAIN_IBEX35":          ("EURUSD", "USD_PER_FOREIGN"),
    "ITALY_FTSEMIB":         ("EURUSD", "USD_PER_FOREIGN"),
    # No matching free bilateral pair -> USD return intentionally left blank:
    # HONGKONG_HSI (HKD), CANADA_TSX (CAD), BRAZIL_BOVESPA (BRL),
    # INDONESIA_JKSE (IDR), MEXICO_IPC (MXN), SINGAPORE_STI (SGD),
    # SAUDI_TASI (SAR), SOUTHAFRICA_JSE (ZAR).
}

# ---------------------------------------------------------------------------
# 2c. VALUATIONS -- Siblis Research free data API (no key needed).
#     Endpoint: {SIBLIS_API_BASE}/{ticker}/{metric}
#     Maps the Siblis index ticker -> our asset_id. Only these twelve indices
#     have free valuation coverage; any index missing from this map simply
#     doesn't appear in the valuation table (never proxied or fabricated).
#
#     Note: Siblis "USA" and "CAN" are broad large-cap aggregates, NOT exactly
#     the S&P 500 / TSX Composite -- surfaced as a caption in the UI.
# ---------------------------------------------------------------------------
SIBLIS_API_BASE = "https://siblisresearch.supabase.co/functions/v1/free-data-api/v1"

VALUATION_TICKERS = {
    "NIFTY": "INDIA_NIFTY50",
    "DAX":   "GERMANY_DAX",
    "CAC":   "FRANCE_CAC40",
    "UKX":   "UK_FTSE100",
    "N225":  "JAPAN_NIKKEI",
    "KOSPI": "SKOREA_KOSPI",
    "HSI":   "HONGKONG_HSI",
    "IBOV":  "BRAZIL_BOVESPA",
    "SSE":   "CHINA_SSE",
    "NDX":   "US_NASDAQ",
    "USA":   "US_SP500",
    "CAN":   "CANADA_TSX",
}

# Only these three metrics work on the free tier. 'pe', 'eps', 'pb' and
# 'dividend-yield' either 400 or return null values -- deliberately not
# requested rather than fetched-and-discarded.
VALUATION_METRICS = ["pe-trailing", "pe-forward", "cape"]

# Display labels for the valuation table / history chart.
VALUATION_LABELS = {
    "pe-trailing": "Trailing PE",
    "pe-forward":  "Forward PE",
    "cape":        "CAPE",
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
