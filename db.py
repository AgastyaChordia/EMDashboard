"""
Storage layer. DuckDB is used because it's embedded (one file, no server),
fast for time-series analytics, and pandas round-trips natively -- a good
fit for a personal dashboard. Swap for Postgres/Timescale later if you need
multi-user access; the interface below is small enough to reimplement.
"""
import os
import certifi
# python.org macOS builds ship without a usable system CA bundle, so urllib
# (fredapi) and requests (World Bank) fail TLS verification out of the box.
# Point both at certifi's bundle. setdefault -> respects an explicit override.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "market.duckdb"
DB_PATH.parent.mkdir(exist_ok=True)


def get_connection():
    return duckdb.connect(str(DB_PATH))


def init_schema():
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            asset_id VARCHAR,
            module VARCHAR,       -- equities | currencies | commodities | fixed_income | risk
            date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            fetched_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS macro_indicators (
            country VARCHAR,
            indicator VARCHAR,
            date DATE,
            value DOUBLE,
            source VARCHAR,
            fetched_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (country, indicator, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS commentary (
            report_date DATE,
            module VARCHAR,
            body TEXT,
            generated_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (report_date, module)
        )
    """)
    con.close()


def upsert_prices(df: pd.DataFrame):
    """df must have columns: asset_id, module, date, open, high, low, close, volume"""
    if df.empty:
        return
    con = get_connection()
    con.register("tmp_prices", df)
    con.execute("""
        INSERT OR REPLACE INTO prices
            (asset_id, module, date, open, high, low, close, volume)
        SELECT asset_id, module, date, open, high, low, close, volume FROM tmp_prices
    """)
    con.close()


def upsert_macro(df: pd.DataFrame):
    """df must have columns: country, indicator, date, value, source"""
    if df.empty:
        return
    con = get_connection()
    con.register("tmp_macro", df)
    con.execute("""
        INSERT OR REPLACE INTO macro_indicators
            (country, indicator, date, value, source)
        SELECT country, indicator, date, value, source FROM tmp_macro
    """)
    con.close()


def save_commentary(report_date, module, body):
    con = get_connection()
    con.execute(
        "INSERT OR REPLACE INTO commentary (report_date, module, body) VALUES (?, ?, ?)",
        [report_date, module, body],
    )
    con.close()


def read_prices(asset_ids=None, module=None) -> pd.DataFrame:
    con = get_connection()
    query = "SELECT * FROM prices WHERE 1=1"
    params = []
    if asset_ids:
        query += " AND asset_id IN (" + ",".join(["?"] * len(asset_ids)) + ")"
        params += list(asset_ids)
    if module:
        query += " AND module = ?"
        params.append(module)
    df = con.execute(query, params).df()
    con.close()
    return df


if __name__ == "__main__":
    init_schema()
    print(f"Schema ready at {DB_PATH}")
