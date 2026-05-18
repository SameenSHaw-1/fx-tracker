#!/usr/bin/env python3
"""
Fetch exchange rates from Chinese banks: BOC, ICBC, ABC.
Outputs data/rates.json and appends to data/history/YYYY-MM-DD.json.
All rates are normalised to: 100 units of foreign currency = X CNY.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

CURRENCIES = ["EUR", "USD", "THB", "JPY", "KRW"]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
RATES_FILE = os.path.join(DATA_DIR, "rates.json")

os.makedirs(HISTORY_DIR, exist_ok=True)

# ─── helpers ───────────────────────────────────────────────────────────────────

def normalise(value: float, currency: str) -> float:
    """
    Bank quotes are per 100 units.  JPY/KRW/THB are already per-100 in most
    bank tables.  If the raw value is per 1 unit, we multiply by 100.
    We detect by magnitude: if value < 1 for JPY/KRW/THB, multiply.
    """
    if currency in ("JPY", "KRW", "THB") and value < 1:
        return round(value * 100, 4)
    return round(value, 4)


def safe_float(text: str) -> float | None:
    """Extract a float from text, returning None on failure."""
    text = text.strip().replace(",", "")
    m = re.search(r"[\d]+\.?\d*", text)
    if m:
        return float(m.group())
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_hm() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M")


# ─── bank scrapers ─────────────────────────────────────────────────────────────

def fetch_boc() -> dict:
    """
    中国银行外汇牌价:
    https://www.boc.cn/sourcedb/whpj/index.html
    """
    url = "https://www.boc.cn/sourcedb/whpj/index.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    rates = {}
    # BOC table: columns typically are
    # 货币名称 | 现汇买入价 | 现钞买入价 | 现汇卖出价 | 现钞卖出价 | 中行折算价(中间价)
    table = soup.find("table")
    if not table:
        raise ValueError("No table found on BOC page")

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        name = cells[0].get_text(strip=True)
        # Map Chinese currency name to code
        name_to_code = {
            "欧元": "EUR", "美元": "USD", "泰国铢": "THB",
            "泰国铢(100)": "THB", "日元": "JPY", "韩国圆": "KRW",
            "韩元": "KRW",
        }
        code = name_to_code.get(name)
        if code and code in CURRENCIES:
            buy = safe_float(cells[1].get_text())
            sell = safe_float(cells[3].get_text())
            mid = safe_float(cells[5].get_text()) if len(cells) > 5 else None
            rates[code] = {
                "buy": normalise(buy, code) if buy else None,
                "sell": normalise(sell, code) if sell else None,
                "mid": normalise(mid, code) if mid else None,
            }

    if not rates:
        raise ValueError("No matching currency rows found on BOC page")
    return rates


def fetch_icbc() -> dict:
    """
    工商银行外汇牌价:
    https://mybank.icbc.com.cn/ICBCDynamicSite/Charts/RmbHQRateQuery.aspx
    ICBC page uses AJAX / JSON endpoint behind the scenes.
    We try multiple approaches.
    """
    url = "https://mybank.icbc.com.cn/ICBCDynamicSite/Charts/RmbHQRateQuery.aspx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    rates = {}
    # ICBC page may render a table with similar structure
    # Look for table with currency data
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 5:
                continue
            name = cells[0].get_text(strip=True)
            name_to_code = {
                "EUR": "EUR", "USD": "USD", "THB": "THB",
                "JPY": "JPY", "KRW": "KRW",
                "欧元": "EUR", "美元": "USD", "日元": "JPY",
                "韩元": "KRW", "泰国铢": "THB",
            }
            code = None
            for key, val in name_to_code.items():
                if key in name.upper() or key == name:
                    code = val
                    break
            if code and code in CURRENCIES:
                # Try to find buy/sell/mid in remaining cells
                texts = [c.get_text(strip=True) for c in cells[1:]]
                buy = sell = mid = None
                for t in texts:
                    v = safe_float(t)
                    if v:
                        if buy is None:
                            buy = v
                        elif sell is None:
                            sell = v
                        elif mid is None:
                            mid = v
                rates[code] = {
                    "buy": normalise(buy, code) if buy else None,
                    "sell": normalise(sell, code) if sell else None,
                    "mid": normalise(mid, code) if mid else None,
                }

    if not rates:
        # Try JSON endpoint
        json_url = "https://mybank.icbc.com.cn/ICBCDynamicSite2/Charts/FxRateList.aspx"
        resp2 = requests.get(json_url, headers=headers, timeout=20)
        if resp2.status_code == 200:
            try:
                data = resp2.json()
                if isinstance(data, list):
                    for item in data:
                        code = item.get("ccyNbr", item.get("currency", "")).upper()
                        if code in CURRENCIES:
                            buy = safe_float(str(item.get("tbpPri", "")))
                            sell = safe_float(str(item.get("tspPri", "")))
                            mid = safe_float(str(item.get("centralRate", item.get("midPri", ""))))
                            rates[code] = {
                                "buy": normalise(buy, code) if buy else None,
                                "sell": normalise(sell, code) if sell else None,
                                "mid": normalise(mid, code) if mid else None,
                            }
            except Exception:
                pass

    if not rates:
        raise ValueError("No matching currency data found on ICBC page")
    return rates


def fetch_abc() -> dict:
    """
    农业银行外汇牌价:
    https://www.abchina.com/cn/foreignExchange/reference/CurrentExchangeRate/
    """
    url = "https://www.abchina.com/cn/foreignExchange/reference/CurrentExchangeRate/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    rates = {}
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 5:
                continue
            name = cells[0].get_text(strip=True)
            name_to_code = {
                "EUR": "EUR", "USD": "USD", "THB": "THB",
                "JPY": "JPY", "KRW": "KRW",
                "欧元": "EUR", "美元": "USD", "日元": "JPY",
                "韩元": "KRW", "泰国铢": "THB",
            }
            code = None
            for key, val in name_to_code.items():
                if key in name.upper() or key == name:
                    code = val
                    break
            if code and code in CURRENCIES:
                texts = [c.get_text(strip=True) for c in cells[1:]]
                buy = sell = mid = None
                for t in texts:
                    v = safe_float(t)
                    if v:
                        if buy is None:
                            buy = v
                        elif sell is None:
                            sell = v
                        elif mid is None:
                            mid = v
                rates[code] = {
                    "buy": normalise(buy, code) if buy else None,
                    "sell": normalise(sell, code) if sell else None,
                    "mid": normalise(mid, code) if mid else None,
                }

    if not rates:
        # Try to find embedded JSON data
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "data" in script.string.lower():
                try:
                    json_match = re.search(r'\[.*\]', script.string)
                    if json_match:
                        data = json.loads(json_match.group())
                        for item in data:
                            code = item.get("code", item.get("currency", "")).upper()
                            if code in CURRENCIES:
                                buy = safe_float(str(item.get("buyRate", "")))
                                sell = safe_float(str(item.get("sellRate", "")))
                                mid = safe_float(str(item.get("midRate", item.get("centralRate", ""))))
                                rates[code] = {
                                    "buy": normalise(buy, code) if buy else None,
                                    "sell": normalise(sell, code) if sell else None,
                                    "mid": normalise(mid, code) if mid else None,
                                }
                except Exception:
                    pass

    if not rates:
        raise ValueError("No matching currency data found on ABC page")
    return rates


# ─── main ──────────────────────────────────────────────────────────────────────

def main():
    now = now_iso()
    timestamp_hm = now_hm()

    all_rates = {}

    # Fetch each bank independently
    bank_fetchers = {
        "BOC": fetch_boc,
        "ICBC": fetch_icbc,
        "ABC": fetch_abc,
    }

    for bank_name, fetcher in bank_fetchers.items():
        try:
            rates = fetcher()
            all_rates[bank_name] = {"status": "ok", **rates}
            print(f"[OK] {bank_name}: fetched {len(rates)} currencies")
        except Exception as e:
            all_rates[bank_name] = {"status": "error", **{c: None for c in CURRENCIES}}
            print(f"[ERR] {bank_name}: {e}", file=sys.stderr)

    # Write rates.json
    output = {
        "updated_at": now,
        "source": "bank_scrape",
        "rates": all_rates,
    }
    with open(RATES_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Written {RATES_FILE}")

    # Append to history
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history_file = os.path.join(HISTORY_DIR, f"{today}.json")

    # Build history record
    record = {"time": timestamp_hm, "source": "bank_scrape"}
    for bank_name in ["BOC", "ICBC", "ABC"]:
        bank_data = all_rates.get(bank_name, {})
        for currency in CURRENCIES:
            cdata = bank_data.get(currency)
            if cdata:
                record[f"{bank_name}_{currency}_mid"] = cdata.get("mid")
                record[f"{bank_name}_{currency}_buy"] = cdata.get("buy")
                record[f"{bank_name}_{currency}_sell"] = cdata.get("sell")
            else:
                record[f"{bank_name}_{currency}_mid"] = None
                record[f"{bank_name}_{currency}_buy"] = None
                record[f"{bank_name}_{currency}_sell"] = None

    # Load existing history or create new
    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    else:
        history = []

    # Avoid duplicate entries at the same time
    if not any(r.get("time") == timestamp_hm for r in history):
        history.append(record)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    print(f"Appended to {history_file}")

    # Print summary
    for bank_name, bank_data in all_rates.items():
        if bank_data["status"] == "ok":
            for currency in CURRENCIES:
                cd = bank_data.get(currency)
                if cd:
                    print(f"  {bank_name} {currency}: buy={cd['buy']} sell={cd['sell']} mid={cd['mid']}")


if __name__ == "__main__":
    main()
