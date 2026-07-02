# Emerging & global markets dashboard

A Python-based dashboard tracking equities, currencies, commodities,
sovereign yields, macro indicators, and risk/sentiment across ~20 global
markets with a BRICS+ focus — plus an AI-generated weekly briefing.

This is **Phase 1** of the full spec (see Roadmap below). It's built so
Phases 2–4 slot into the same architecture without a rewrite.

## Architecture

```
ingest/          -- pulls raw data from external APIs, writes to DuckDB
  market_data.py   Yahoo Finance: equities, FX, commodities, VIX
  fixed_income.py  FRED: sovereign yields, credit spreads
  macro.py         World Bank: GDP, inflation, current account, debt
transform/
  analytics.py     reads DuckDB, computes returns/drawdown/vol/correlation
                    (no network calls -- pure computation on stored data)
ai/
  commentary.py     Claude API call that narrates the computed metrics
                     into a weekly written briefing
dashboard/
  app.py            Streamlit UI, reads only from DuckDB
db.py               DuckDB schema + read/write helpers
config.py           every ticker, country, and indicator the system tracks
run_weekly.py       orchestrates all of the above in one command
```

Data flows one direction: ingest → storage → transform → AI → dashboard.
Nothing downstream calls an external API directly, so the dashboard stays
fast and works even if a data source is temporarily down.

## Setup

```bash
pip install -r requirements.txt

# Free API keys needed:
export FRED_API_KEY=...        # https://fred.stlouisfed.org/docs/api/api_key.html
export ANTHROPIC_API_KEY=...   # https://console.anthropic.com

python db.py                   # creates the DuckDB schema
python run_weekly.py           # runs all ingestion + generates the briefing
streamlit run dashboard/app.py # opens the dashboard
```

Run each ingest script individually while you're setting things up
(`python -m ingest.market_data`, etc.) so you can see exactly what fails —
Yahoo Finance ticker availability shifts occasionally, and it's easier to
fix one broken ticker in `config.py` than debug a full run.

## Getting weekly updates automatically

Three options, in order of effort:

1. **GitHub Actions** (included, `.github/workflows/weekly-refresh.yml`) —
   push this repo to GitHub, add `FRED_API_KEY` and `ANTHROPIC_API_KEY` as
   repo secrets, and it runs every Monday automatically, committing the
   updated database back to the repo.
2. **Cron on your own machine/server** — `0 6 * * 1 cd /path/to/em-dashboard && python run_weekly.py`
3. **Claude's own recurring task scheduler** — point it at `run_weekly.py`
   in a Claude Code/Cowork environment with repo access.

## Data source honesty

Not everything in the original spec has a good free source. Here's what's
solid vs. what has real gaps in Phase 1:

| Solid (free, reliable) | Gaps to know about |
|---|---|
| Equity index prices (Yahoo Finance) | Russia excluded — not on Western free feeds since 2022 |
| Major currency pairs | Saudi (TASI) ticker coverage on Yahoo is inconsistent — verify |
| Commodity futures (energy, metals, ag) | Aluminium/Lithium/Nickel are ETF proxies, not pure futures prices |
| US Treasury yields (FRED) | China/India/Brazil/Korea 10Y — no reliable free daily series |
| VIX | MOVE index ticker availability on Yahoo is inconsistent |
| World Bank macro (GDP, inflation, etc.) | Annual data only — not weekly-moving |

## Roadmap — Phases 2–4

**Phase 2** (mostly free, some gaps): risk/sentiment expansion (Fear &
Greed via scraping — check terms of service), economic calendar (Trading
Economics free tier is limited; consider a paid plan if this matters).

**Phase 3** (needs a fundamentals API): valuation (PE, CAPE, EV/EBITDA),
earnings & growth, sectors, individual companies. Financial Modeling Prep,
Simfin, or similar — free tiers exist but are rate-limited; budget for a
paid plan if you want full top-20-market coverage.

**Phase 4** (largest data gaps): ETF/fund flows are mostly paid data
(ETF.com, ycharts, EPFR) — there isn't a good free substitute. The AI daily
commentary in `ai/commentary.py` already works for Phase 1 data; extend the
prompt as Phases 2–3 add more context.

## A note on accuracy

`ai/commentary.py` is instructed to only narrate numbers it's given, never
to recall or estimate a figure. Keep it that way as you extend the prompt —
the value of this system is that every number traces back to a specific
API pull with a timestamp, not to a language model's memory.
