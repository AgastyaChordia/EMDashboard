"""
Generates the weekly AI market commentary. This is the layer that turns
numbers into a written briefing -- it never invents a figure, it only
narrates figures pulled from transform/analytics.py and db.py.

Needs an Anthropic API key:
    export ANTHROPIC_API_KEY=your_key_here
"""
import os
import sys
from datetime import date
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import anthropic
import pandas as pd

from transform.analytics import period_returns, volatility, correlation_matrix
from db import save_commentary

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a markets analyst writing a concise weekly briefing.
Rules:
- Only reference numbers given to you in the data below. Never estimate or
  recall a figure from memory.
- Structure: Overnight/weekly summary, key drivers, top movers, risks to
  monitor, notable opportunities, one line of advisor talking points.
- Be specific with numbers (e.g. "Nikkei +2.1% over the week") not vague
  ("markets were up").
- Keep it under 400 words. Plain prose, no markdown headers.
"""


def _format_data_block() -> str:
    parts = []

    eq = period_returns("equities")
    if not eq.empty:
        parts.append("EQUITY INDEX RETURNS (%):\n" + eq.round(2).to_string())

    fx = period_returns("currencies")
    if not fx.empty:
        parts.append("CURRENCY RETURNS (%):\n" + fx.round(2).to_string())

    cmd = period_returns("commodities")
    if not cmd.empty:
        parts.append("COMMODITY RETURNS (%):\n" + cmd.round(2).to_string())

    vol = volatility("equities")
    if not vol.empty:
        parts.append("EQUITY VOLATILITY, 21D ANNUALIZED (%):\n" + vol.round(2).to_string())

    risk = period_returns("risk_sentiment")
    if not risk.empty:
        parts.append("RISK/SENTIMENT INDEX MOVES (%):\n" + risk.round(2).to_string())

    if not parts:
        return ""
    return "\n\n".join(parts)


def generate_weekly_commentary() -> str:
    data_block = _format_data_block()
    if not data_block:
        return ("No data available yet -- run the ingest scripts first "
                "(ingest/market_data.py, ingest/fixed_income.py, ingest/macro.py).")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    message = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Here is this week's data:\n\n{data_block}\n\n"
                       f"Write the weekly briefing."
        }],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    save_commentary(date.today(), "weekly_briefing", text)
    return text


if __name__ == "__main__":
    print(generate_weekly_commentary())
