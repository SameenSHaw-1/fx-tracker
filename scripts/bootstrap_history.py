#!/usr/bin/env python3
"""
Bootstrap 180 days of historical exchange rate data from frankfurter.app.
Each day is saved as data/history/YYYY-MM-DD.json.
Returns rates as 100 foreign currency = X CNY.
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

os.makedirs(HISTORY_DIR, exist_ok=True)


def fetch_frankfurter(date_str: str) -> dict | None:
    """
    Fetch rates from frankfurter.app for a given date.
    API returns: {"rates": {"EUR": 0.xxxx, ...}} (CNY -> foreign)
    We invert: 1 foreign = (1 / rate) CNY, then multiply by 100.
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
                # rates[currency] = X foreign per 1 CNY
                # 1 foreign = 1/X CNY
                # 100 foreign = 100/X CNY
                inverted = round(100.0 / rates[currency], 4)
                result[currency] = inverted
        return result
    except Exception as e:
        print(f"  Failed to fetch {date_str}: {e}")
        return None


def main():
    today = datetime.now(timezone.utc)
    dates = []
    for i in range(180):
        d = today - timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        dates.append(date_str)

    print(f"Bootstrapping {len(dates)} days of history...")

    for date_str in dates:
        history_file = os.path.join(HISTORY_DIR, f"{date_str}.json")

        if os.path.exists(history_file):
            print(f"  Skipping {date_str} (already exists)")
            continue

        rates = fetch_frankfurter(date_str)
        if rates is None:
            continue

        # Build record with all banks having the same values
        record = {"time": "12:00", "source": "market_rate"}
        for bank in BANKS:
            for currency in CURRENCIES:
                val = rates.get(currency)
                record[f"{bank}_{currency}_mid"] = val
                record[f"{bank}_{currency}_buy"] = val
                record[f"{bank}_{currency}_sell"] = val

        with open(history_file, "w", encoding="utf-8") as f:
            json.dump([record], f, indent=2, ensure_ascii=False)

        vals = ", ".join(f"{c}={rates[c]}" for c in CURRENCIES if c in rates)
        print(f"  {date_str}: {vals}")

        # Be polite to the API
        time.sleep(0.3)

    print("Bootstrap complete!")


if __name__ == "__main__":
    main()
