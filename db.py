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

import uuid
from datetime import datetime

import duckdb
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "market.duckdb"
DB_PATH.parent.mkdir(exist_ok=True)

# A 'running' fetch flag whose heartbeat is older than this is treated as a
# crashed/interrupted run: the next caller may take it over (and resume it)
# instead of being blocked forever.
STALE_FETCH_SECONDS = 1800  # 30 min


def get_secret(key: str, default=None):
    """Read a secret/API key. Checks os.environ first (local .zshrc, cron,
    GitHub Actions), then falls back to st.secrets when running inside
    Streamlit -- Streamlit Cloud provides secrets via st.secrets, not env
    vars. Importing streamlit is lazy so CLI/ingest runs stay lightweight.
    """
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        # No streamlit runtime / no secrets file configured -- fine.
        pass
    return default


def get_connection():
    return duckdb.connect(str(DB_PATH))


def has_price_data() -> bool:
    """True if the prices table exists and holds at least one row. Used by
    the dashboard to decide whether to show the first-run 'fetch data' state
    (e.g. on a fresh Streamlit Cloud deploy where the DuckDB file wasn't
    committed to git)."""
    con = get_connection()
    try:
        return con.execute("SELECT COUNT(*) FROM prices").fetchone()[0] > 0
    except Exception:
        return False
    finally:
        con.close()


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
    # Valuation multiples get their own table rather than riding in `prices`:
    # prices is keyed (asset_id, date), which can't hold three metrics for the
    # same index on the same date. Same shape as macro_indicators.
    con.execute("""
        CREATE TABLE IF NOT EXISTS valuations (
            asset_id VARCHAR,
            metric VARCHAR,       -- pe-trailing | pe-forward | cape
            date DATE,
            value DOUBLE,
            source VARCHAR,
            fetched_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (asset_id, metric, date)
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


# --------------------------------------------------------------------------
# Fetch coordination: a single-row lock + a per-ticker progress log. These let
# the Streamlit UI run the (slow, rate-limit-prone) ingest safely on shared
# cloud infra -- one fetch at a time, resumable after an interruption, and
# never overlapping schema init. Kept separate from init_schema() so the flag
# can be inspected before deciding whether to (re)init the heavy tables.
# --------------------------------------------------------------------------
def init_control_schema():
    """Create the fetch-coordination tables and seed the singleton lock row.
    Cheap and always safe to call; must run before any lock/progress helper."""
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS fetch_control (
            id INTEGER PRIMARY KEY,     -- always 1 (singleton)
            status VARCHAR,             -- 'idle' | 'running'
            run_id VARCHAR,
            started_at TIMESTAMP,
            heartbeat TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS fetch_progress (
            run_id VARCHAR,
            asset_id VARCHAR,
            module VARCHAR,
            ticker VARCHAR,
            status VARCHAR,             -- 'success' | 'failed'
            reason VARCHAR,
            updated_at TIMESTAMP,
            PRIMARY KEY (run_id, asset_id)
        )
    """)
    con.execute("""
        INSERT INTO fetch_control (id, status)
        SELECT 1, 'idle'
        WHERE NOT EXISTS (SELECT 1 FROM fetch_control WHERE id = 1)
    """)
    con.close()


def is_fetch_running(stale_after: int = STALE_FETCH_SECONDS) -> bool:
    """True if a fetch holds the lock AND its heartbeat is still fresh. A stale
    heartbeat (crashed run) reads as not-running so the UI can offer a restart."""
    con = get_connection()
    try:
        row = con.execute(
            "SELECT status, heartbeat FROM fetch_control WHERE id = 1").fetchone()
    except Exception:
        return False
    finally:
        con.close()
    if not row or row[0] != "running":
        return False
    hb = row[1]
    if hb is None:
        return True
    return (datetime.utcnow() - hb).total_seconds() < stale_after


def try_begin_fetch(stale_after: int = STALE_FETCH_SECONDS):
    """Atomically move the singleton lock idle->running. Returns
    (acquired: bool, run_id: str|None, resumed: bool):

    - lock idle            -> start a fresh run (new run_id, old progress
                              cleared), acquired=True, resumed=False.
    - running, heartbeat   -> another session owns it; acquired=False.
      still fresh
    - running, heartbeat   -> crashed run: take it over KEEPING its run_id so
      stale                   its already-fetched tickers can be skipped,
                              acquired=True, resumed=True.

    The check-and-set runs in one transaction; if two callers race, DuckDB's
    MVCC makes one commit conflict and we report it as not-acquired."""
    con = get_connection()
    now = datetime.utcnow()
    try:
        con.execute("BEGIN")
        row = con.execute(
            "SELECT status, run_id, heartbeat FROM fetch_control WHERE id = 1"
        ).fetchone()
        status = row[0] if row else "idle"
        run_id = row[1] if row else None
        hb = row[2] if row else None
        if (status == "running" and hb is not None
                and (now - hb).total_seconds() < stale_after):
            con.execute("ROLLBACK")
            return (False, None, False)
        resumed = status == "running" and bool(run_id)
        if not resumed:
            run_id = uuid.uuid4().hex
            # Fresh run: drop any progress rows from earlier runs so the
            # "X of Y" counts and the skip set start clean.
            con.execute("DELETE FROM fetch_progress WHERE run_id <> ?", [run_id])
        con.execute(
            "UPDATE fetch_control SET status='running', run_id=?, "
            "started_at=?, heartbeat=? WHERE id = 1", [run_id, now, now])
        con.execute("COMMIT")
        return (True, run_id, resumed)
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        return (False, None, False)
    finally:
        con.close()


def heartbeat_fetch(run_id: str):
    """Refresh the lock's heartbeat so a long-but-healthy run isn't mistaken
    for a crashed one. No-op if we no longer own the lock."""
    con = get_connection()
    try:
        con.execute("UPDATE fetch_control SET heartbeat=? WHERE id=1 AND run_id=?",
                    [datetime.utcnow(), run_id])
    finally:
        con.close()


def end_fetch(run_id: str):
    """Release the lock (back to idle) after a run completes. Only clears it if
    we still own this run_id."""
    con = get_connection()
    try:
        con.execute(
            "UPDATE fetch_control SET status='idle', heartbeat=? "
            "WHERE id=1 AND run_id=?", [datetime.utcnow(), run_id])
    finally:
        con.close()


def succeeded_asset_ids(run_id: str) -> set:
    """asset_ids already fetched successfully in this run -- the skip set that
    makes a resumed fetch avoid re-doing completed work."""
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT asset_id FROM fetch_progress "
            "WHERE run_id=? AND status='success'", [run_id]).fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def write_ticker_batch(price_df, run_id, asset_id, module, ticker,
                       status, reason=None):
    """Write one ticker's price rows AND its progress marker in a SINGLE
    transaction, so a ticker is only ever recorded 'success' if its data
    actually committed. That atomicity is what makes resume correct, and using
    one short transaction per ticker keeps writes from overlapping schema init.
    """
    con = get_connection()
    try:
        con.execute("BEGIN")
        if price_df is not None and not price_df.empty:
            con.register("tmp_batch", price_df)
            con.execute("""
                INSERT OR REPLACE INTO prices
                    (asset_id, module, date, open, high, low, close, volume)
                SELECT asset_id, module, date, open, high, low, close, volume
                FROM tmp_batch
            """)
            con.unregister("tmp_batch")
        con.execute("""
            INSERT OR REPLACE INTO fetch_progress
                (run_id, asset_id, module, ticker, status, reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [run_id, asset_id, module, ticker, status, reason,
              datetime.utcnow()])
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
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


def upsert_valuations(df: pd.DataFrame):
    """df must have columns: asset_id, metric, date, value, source"""
    if df.empty:
        return
    con = get_connection()
    con.register("tmp_val", df)
    con.execute("""
        INSERT OR REPLACE INTO valuations (asset_id, metric, date, value, source)
        SELECT asset_id, metric, date, value, source FROM tmp_val
    """)
    con.close()


def read_valuations(asset_ids=None, metrics=None) -> pd.DataFrame:
    con = get_connection()
    query = "SELECT * FROM valuations WHERE 1=1"
    params = []
    if asset_ids:
        query += " AND asset_id IN (" + ",".join(["?"] * len(asset_ids)) + ")"
        params += list(asset_ids)
    if metrics:
        query += " AND metric IN (" + ",".join(["?"] * len(metrics)) + ")"
        params += list(metrics)
    try:
        df = con.execute(query, params).df()
    except Exception:
        # Table not created yet (pre-existing DB that hasn't been re-inited).
        df = pd.DataFrame()
    finally:
        con.close()
    return df


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
