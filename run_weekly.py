"""
The single entry point for the weekly refresh. This is what you point a
cron job / GitHub Action / Claude scheduled task at.

    python run_weekly.py
"""
import sys
import traceback
from datetime import datetime

def main():
    print(f"=== Weekly refresh started {datetime.now().isoformat()} ===")

    steps = [
        ("Equities/currencies/commodities/risk (Yahoo Finance)",
         "ingest.market_data", "run"),
        ("Sovereign yields & credit spreads (FRED)",
         "ingest.fixed_income", "run"),
        ("Macro indicators (World Bank)",
         "ingest.macro", "run"),
    ]

    for label, module_name, func_name in steps:
        print(f"\n--- {label} ---")
        try:
            module = __import__(module_name, fromlist=[func_name])
            getattr(module, func_name)()
        except Exception:
            print(f"[FAILED] {label}")
            traceback.print_exc()
            # Continue with other steps rather than aborting the whole run --
            # a failed FX pull shouldn't block the macro pull.

    print("\n--- AI weekly commentary ---")
    try:
        from ai.commentary import generate_weekly_commentary
        text = generate_weekly_commentary()
        print(text)
    except Exception:
        print("[FAILED] AI commentary")
        traceback.print_exc()

    print(f"\n=== Weekly refresh finished {datetime.now().isoformat()} ===")


if __name__ == "__main__":
    main()
