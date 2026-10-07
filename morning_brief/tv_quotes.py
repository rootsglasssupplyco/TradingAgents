"""Fetch delayed quotes for US tickers and the main indices from TradingView's public scanner.

Usage: python3 tv_quotes.py VOO SCHD NVDA ...
Prints JSON: {"indices": [...], "quotes": {TICKER: {...}}, "missing": [...], "error": null}
Needs network access to scanner.tradingview.com. Standard library only.
"""
import json
import sys
import urllib.request

URL = "https://scanner.tradingview.com/america/scan"
FULL = ["name", "exchange", "description", "close", "change", "dividends_yield_current", "dividends_yield",
        "Recommend.All", "RSI", "SMA200", "price_52_week_high", "price_52_week_low"]
BASIC = ["name", "exchange", "description", "close", "change"]
EXCHANGE_RANK = {"NASDAQ": 0, "NYSE": 0, "AMEX": 1, "CBOE": 2, "BATS": 2}


INDICES = {"SP:SPX": "S&P 500", "NASDAQ:IXIC": "Nasdaq", "DJ:DJI": "Dow", "TVC:US10Y": "10-yr yield"}


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("data", [])


def scan(tickers, columns):
    return post(URL, {"filter": [{"left": "name", "operation": "in_range", "right": tickers}],
                      "columns": columns, "range": [0, 500]})


def indices():
    try:
        rows = post("https://scanner.tradingview.com/global/scan",
                    {"symbols": {"tickers": list(INDICES)}, "columns": ["close", "change"]})
    except Exception:
        return []
    out = []
    for row in rows:
        close, change = (row.get("d") or [None, None])[:2]
        out.append({"name": INDICES.get(row.get("s"), row.get("s")), "level": close,
                    "changePct": round(change, 2) if change is not None else None})
    return out


def rating(v):
    if v is None:
        return None
    return ("Strong sell" if v < -0.5 else "Sell" if v < -0.1 else
            "Neutral" if v <= 0.1 else "Buy" if v <= 0.5 else "Strong buy")


def main(tickers):
    tickers = sorted({t.upper() for t in tickers})
    idx = indices()
    try:
        cols, rows = FULL, scan(tickers, FULL)
    except Exception:
        try:
            cols, rows = BASIC, scan(tickers, BASIC)
        except Exception as e:
            return {"indices": idx, "quotes": {}, "missing": tickers, "error": str(e)}
    best = {}
    for row in rows:
        d = dict(zip(cols, row.get("d", [])))
        name, rank = d.get("name"), EXCHANGE_RANK.get(d.get("exchange"), 9)
        if name in tickers and (name not in best or rank < best[name][0]):
            best[name] = (rank, d)
    quotes = {}
    for name, (_, d) in best.items():
        dy = d.get("dividends_yield_current")
        dy = d.get("dividends_yield") if dy is None else dy
        quotes[name] = {
            "price": d.get("close"),
            "changePct": round(d["change"], 2) if d.get("change") is not None else None,
            "dividendYield": round(dy, 2) if dy is not None else None,
            "tvRating": rating(d.get("Recommend.All")),
            "rsi": round(d["RSI"], 1) if d.get("RSI") is not None else None,
            "sma200": d.get("SMA200"),
            "high52": d.get("price_52_week_high"),
            "low52": d.get("price_52_week_low"),
            "exchange": d.get("exchange"),
            "name": d.get("description"),
        }
    return {"indices": idx, "quotes": quotes, "missing": [t for t in tickers if t not in quotes], "error": None}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1:]), indent=1))
