#!/usr/bin/env python3
"""
Fetch exchange rates from free public APIs that are accessible from GitHub Actions.

Primary source: frankfurter.app (free, no key, CORS-friendly)
The rates represent interbank/market rates, NOT official bank buying/selling prices.
We simulate buy/sell spread based on typical bank spreads for each currency.

All rates normalised to: 100 units of foreign currency = X CNY
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

CURRENCIES = ["EUR", "USD", "THB", "JPY", "KRW"]

# Typical spread percentage for each currency (half-spread each side of mid)
# Based on approximate Chinese bank spreads
SPREAD = {
    "EUR": 0.0035,   # ~0.35% each side
    "USD": 0.0020,   # ~0.20% each side
    "THB": 0.0100,   # ~1.00% each side
    "JPY": 0.0040,   # ~0.40% each side
    "KRW": 0.0150,   # ~1.50% each side
}

# Small random-like offsets per bank to differentiate (fixed seeds for consistency)
BANK_OFFSETS = {
    "BOC":  {"EUR": 0.0000, "USD": 0.0000, "THB": 0.0000, "JPY": 0.0000, "KRW": 0.0000},
    "ICBC": {"EUR": 0.0003, "USD": 0.0002, "THB": 0.0005, "JPY": 0.0002, "KRW": 0.0008},
    "ABC":  {"EUR":-0.0002, "USD":-0.0001, "THB":-0.0003, "JPY":-0.0001, "KRW":-0.0005},
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
RATES_FILE = os.path.join(DATA_DIR, "rates.json")

os.makedirs(HISTORY_DIR, exist_ok=True)


def now_iso() -> str:
    tz_cst = timezone(timedelta(hours=8))
    return datetime.now(tz_cst).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def now_hm() -> str:
    tz_cst = timezone(timedelta(hours=8))
    return datetime.now(tz_cst).strftime("%H:%M")


def today_cst() -> str:
    tz_cst = timezone(timedelta(hours=8))
    return datetime.now(tz_cst).strftime("%Y-%m-%d")


def fetch_market_rates() -> dict[str, float]:
    """
    Fetch latest CNY-based rates from frankfurter.app.
    Returns dict: {"EUR": <100 units in CNY>, "USD": ..., ...}
    """
    url = "https://api.frankfurter.app/latest?from=CNY&symbols=EUR,USD,JPY,KRW,THB"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    # data["rates"] is CNY -> foreign, e.g. {"EUR": 0.1280, "USD": 0.1380, ...}
    # We need foreign -> CNY per 100 units = (1 / rate) * 100
    result = {}
    for currency, cny_per_foreign_inv in data["rates"].items():
        if currency in CURRENCIES and cny_per_foreign_inv > 0:
            per_100 = round((1.0 / cny_per_foreign_inv) * 100, 4)
            result[currency] = per_100

    return result


def make_bank_rates(mid_rates: dict[str, float], bank: str) -> dict:
    """
    Given mid rates per 100 units, compute buy/sell with spread + bank offset.
    """
    bank_data = {"status": "ok"}
    offset_map = BANK_OFFSETS.get(bank, {})

    for currency in CURRENCIES:
        mid = mid_rates.get(currency)
        if mid is None:
            bank_data[currency] = None
            continue

        spread_pct = SPREAD.get(currency, 0.005)
        offset = offset_map.get(currency, 0.0)

        adjusted_mid = round(mid * (1 + offset), 4)
        buy = round(adjusted_mid * (1 - spread_pct), 4)
        sell = round(adjusted_mid * (1 + spread_pct), 4)

        bank_data[currency] = {
            "buy": buy,
            "sell": sell,
            "mid": adjusted_mid,
        }

    return bank_data


def main():
    print("Fetching market rates from frankfurter.app...")

    try:
        mid_rates = fetch_market_rates()
        print(f"[OK] Market rates: {mid_rates}")
    except Exception as e:
        print(f"[ERR] Failed to fetch market rates: {e}", file=sys.stderr)
        sys.exit(1)

    all_rates = {}
    for bank in ["BOC", "ICBC", "ABC"]:
        all_rates[bank] = make_bank_rates(mid_rates, bank)
        print(f"[OK] {bank} rates computed")

    output = {
        "updated_at": now_iso(),
        "source": "market_rate",
        "note": "汇率来源：市场汇率（frankfurter.app），买卖价基于典型银行点差模拟，仅供参考",
        "rates": all_rates,
    }

    with open(RATES_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Written {RATES_FILE}")

    # Append to history
    today = today_cst()
    history_file = os.path.join(HISTORY_DIR, f"{today}.json")
    timestamp_hm = now_hm()

    record = {"time": timestamp_hm, "source": "market_rate"}
    for bank in ["BOC", "ICBC", "ABC"]:
        bank_data = all_rates.get(bank, {})
        for currency in CURRENCIES:
            cdata = bank_data.get(currency)
            if cdata and isinstance(cdata, dict):
                record[f"{bank}_{currency}_mid"] = cdata.get("mid")
                record[f"{bank}_{currency}_buy"] = cdata.get("buy")
                record[f"{bank}_{currency}_sell"] = cdata.get("sell")
            else:
                record[f"{bank}_{currency}_mid"] = None
                record[f"{bank}_{currency}_buy"] = None
                record[f"{bank}_{currency}_sell"] = None

    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    else:
        history = []

    if not any(r.get("time") == timestamp_hm for r in history):
        history.append(record)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"Appended to {history_file}")

    # Print summary
    for bank in ["BOC", "ICBC", "ABC"]:
        for currency in CURRENCIES:
            cd = all_rates[bank].get(currency)
            if cd and isinstance(cd, dict):
                print(f"  {bank} {currency}: buy={cd['buy']} sell={cd['sell']} mid={cd['mid']}")


if __name__ == "__main__":
    main()
