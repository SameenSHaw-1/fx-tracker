#!/usr/bin/env python3
"""
Bootstrap 180 days of historical exchange rate data from frankfurter.app.
Each day is saved as data/history/YYYY-MM-DD.json.
All rates are normalised to: 100 units of foreign currency = X CNY.

Run once before first deploy:
    python3 scripts/bootstrap_history.py
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests

CURRENCIES = ["EUR", "USD", "JPY", "KRW", "THB"]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
HISTORY_DIR = os.path.join(ROOT_DIR, "data", "history")

BANKS = ["BOC", "ICBC", "ABC"]

# Typical half-spread per bank per currency (fraction of mid)
# Used to differentiate buy/sell prices and slightly offset bank mids
SPREAD = {
    "EUR": 0.0035,
    "USD": 0.0020,
    "THB": 0.0100,
    "JPY": 0.0040,
    "KRW": 0.0150,
}

# Small mid-price offsets per bank to make chart lines visibly distinct
BANK_OFFSETS = {
    "BOC":  {"EUR": 0.0000, "USD": 0.0000, "THB": 0.0000, "JPY": 0.0000, "KRW": 0.0000},
    "ICBC": {"EUR": 0.0003, "USD": 0.0002, "THB": 0.0005, "JPY": 0.0002, "KRW": 0.0008},
    "ABC":  {"EUR":-0.0002, "USD":-0.0001, "THB":-0.0003, "JPY":-0.0001, "KRW":-0.0005},
}

os.makedirs(HISTORY_DIR, exist_ok=True)


def fetch_frankfurter(date_str: str) -> dict | None:
    """
    Fetch rates from frankfurter.app for a given date.
    API: GET /YYYY-MM-DD?from=CNY&symbols=EUR,USD,...
    Response: {"rates": {"EUR": 0.1280, ...}}  ← X foreign per 1 CNY

    We need: 100 foreign = X CNY
    So: result = (1 / rate) * 100
    e.g. EUR: 1 CNY = 0.128 EUR  →  1 EUR = 7.8125 CNY  →  100 EUR = 781.25 CNY
    e.g. KRW: 1 CNY = 210 KRW   →  1 KRW = 0.00476 CNY →  100 KRW = 47.6 CNY ✓
    """
    url = f"https://api.frankfurter.app/{date_str}"
    params = {"from": "CNY", "symbols": ",".join(CURRENCIES)}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        result = {}
        for currency in CURRENCIES:
            if currency in rates and rates[currency] > 0:
                # (1 / X_foreign_per_cny) * 100 = 100 foreign in CNY
                per_100 = round((1.0 / rates[currency]) * 100, 4)
                result[currency] = per_100
        return result
    except Exception as e:
        print(f"  Failed to fetch {date_str}: {e}")
        return None


def make_bank_record(mid_rates: dict, bank: str, time_str: str) -> dict:
    """Build a history record for one bank with buy/sell spread applied."""
    record: dict = {}
    offset_map = BANK_OFFSETS.get(bank, {})
    for currency in CURRENCIES:
        mid = mid_rates.get(currency)
        if mid is None:
            record[f"{bank}_{currency}_mid"] = None
            record[f"{bank}_{currency}_buy"] = None
            record[f"{bank}_{currency}_sell"] = None
            continue
        spread_pct = SPREAD.get(currency, 0.005)
        offset = offset_map.get(currency, 0.0)
        adj_mid = round(mid * (1 + offset), 4)
        record[f"{bank}_{currency}_mid"] = adj_mid
        record[f"{bank}_{currency}_buy"] = round(adj_mid * (1 - spread_pct), 4)
        record[f"{bank}_{currency}_sell"] = round(adj_mid * (1 + spread_pct), 4)
    return record


def main() -> None:
    today = datetime.now(timezone.utc)
    dates = []
    for i in range(180):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))

    print(f"Bootstrapping {len(dates)} days of history...")
    skipped = 0
    written = 0
    failed = 0

    for date_str in dates:
        history_file = os.path.join(HISTORY_DIR, f"{date_str}.json")

        if os.path.exists(history_file):
            skipped += 1
            continue

        mid_rates = fetch_frankfurter(date_str)
        if mid_rates is None:
            failed += 1
            continue

        # Build combined record for all banks
        record: dict = {"time": "12:00", "source": "market_rate"}
        for bank in BANKS:
            record.update(make_bank_record(mid_rates, bank, "12:00"))

        with open(history_file, "w", encoding="utf-8") as f:
            json.dump([record], f, indent=2, ensure_ascii=False)

        vals = " | ".join(f"{c}={mid_rates[c]}" for c in CURRENCIES if c in mid_rates)
        print(f"  {date_str}: {vals}")
        written += 1

        # Rate-limit: be polite to the free API
        time.sleep(0.35)

    print(f"\nDone. Written: {written}, Skipped: {skipped}, Failed: {failed}")
    if skipped > 0:
        print("Tip: delete existing history files and re-run to regenerate with corrected values.")


if __name__ == "__main__":
    main()
