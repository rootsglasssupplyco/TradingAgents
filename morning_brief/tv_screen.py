"""Screen US stocks on TradingView for two buy setups, plus history for current holdings.

  python3 tv_screen.py screen            -> {"value": [...], "momentum": [...]}
  python3 tv_screen.py history T=SHARES ... -> past values of these holdings (1W..1Y ago)

value:    profitable, growing, analysts see 25%+ upside, priced at or below its own trend
momentum: early uptrend (50-day just crossed above 200-day), breaking toward 52-week highs
          on rising volume, not yet overbought
Results are candidates for research, not buy signals. Standard library only.
"""
import json
import sys
import urllib.request

URL = "https://scanner.tradingview.com/america/scan"
COLS = ["name", "description", "sector", "close", "change", "market_cap_basic", "price_earnings_ttm",
        "earnings_per_share_diluted_yoy_growth_ttm", "total_revenue_yoy_growth_ttm", "debt_to_equity",
        "price_target_average", "recommendation_mark", "SMA50", "SMA200", "RSI", "Perf.1M", "Perf.3M",
        "Perf.Y", "price_52_week_high", "price_52_week_low", "relative_volume_10d_calc",
        "dividends_yield_current"]
BASE = [
    {"left": "type", "operation": "equal", "right": "stock"},
    {"left": "is_primary", "operation": "equal", "right": True},
    {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
]


def post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("data", [])


def rows(filters, n=600):
    data = post({"filter": BASE + filters, "columns": COLS, "range": [0, n],
                 "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}})
    return [dict(zip(COLS, r["d"])) for r in data]


def r1(v):
    return round(v, 1) if isinstance(v, (int, float)) else None


def card(d, setup, score):
    close, target = d["close"], d.get("price_target_average")
    return {
        "setup": setup, "ticker": d["name"], "name": d["description"], "sector": d["sector"],
        "price": close, "upsidePct": r1((target / close - 1) * 100) if target and close else None,
        "analystMark": r1(d.get("recommendation_mark")), "pe": r1(d.get("price_earnings_ttm")),
        "epsGrowth": r1(d.get("earnings_per_share_diluted_yoy_growth_ttm")),
        "revGrowth": r1(d.get("total_revenue_yoy_growth_ttm")), "rsi": r1(d.get("RSI")),
        "perf1M": r1(d.get("Perf.1M")), "perf3M": r1(d.get("Perf.3M")), "perfY": r1(d.get("Perf.Y")),
        "sma50": r1(d.get("SMA50")), "sma200": r1(d.get("SMA200")),
        "high52": d.get("price_52_week_high"), "relVolume": r1(d.get("relative_volume_10d_calc")),
        "dividendYield": r1(d.get("dividends_yield_current")),
        "marketCapB": r1(d["market_cap_basic"] / 1e9), "score": round(score, 2),
    }


def value_screen():
    out = []
    for d in rows([
        {"left": "market_cap_basic", "operation": "greater", "right": 5e9},
        {"left": "price_earnings_ttm", "operation": "in_range", "right": [3, 30]},
        {"left": "earnings_per_share_diluted_yoy_growth_ttm", "operation": "greater", "right": 10},
        {"left": "recommendation_mark", "operation": "less", "right": 2},
    ]):
        close, target = d["close"], d.get("price_target_average")
        if not (close and target and d.get("SMA200")):
            continue
        upside = target / close - 1
        if upside < 0.25 or close > d["SMA200"] * 1.05 or (d.get("debt_to_equity") or 0) > 1.5:
            continue
        if (d.get("Perf.1M") or 0) < -15:
            continue  # still in free fall; wait for it to stabilize
        peg = d["price_earnings_ttm"] / max(d["earnings_per_share_diluted_yoy_growth_ttm"], 1)
        stabilizing = 0.5 if (d.get("RSI") or 0) >= 40 else 0
        out.append(card(d, "Value", upside * 2 - peg + (2 - d["recommendation_mark"]) + stabilizing))
    return sorted(out, key=lambda c: -c["score"])[:10]


def momentum_screen():
    out = []
    for d in rows([
        {"left": "market_cap_basic", "operation": "greater", "right": 2e9},
        {"left": "close", "operation": "greater", "right": "SMA50"},
        {"left": "SMA50", "operation": "greater", "right": "SMA200"},
        {"left": "RSI", "operation": "in_range", "right": [55, 70]},
        {"left": "Perf.1M", "operation": "greater", "right": 5},
        {"left": "total_revenue_yoy_growth_ttm", "operation": "greater", "right": 10},
    ]):
        sma50, sma200, high = d["SMA50"], d["SMA200"], d.get("price_52_week_high")
        perf3m, relvol = d.get("Perf.3M") or 0, d.get("relative_volume_10d_calc") or 0
        if not (high and sma200) or sma50 / sma200 > 1.12 or not 0 < perf3m <= 45:
            continue  # trend already mature, stretched, or not really up
        if d["close"] < high * 0.90 or relvol < 0.9:
            continue  # not breaking out, or no volume behind it
        freshness = 1.12 - sma50 / sma200
        out.append(card(d, "Early momentum", freshness * 10 + relvol + d["Perf.1M"] / 10))
    return sorted(out, key=lambda c: -c["score"])[:10]


def history(pairs):
    shares = {t.upper(): float(s) for t, s in (p.split("=") for p in pairs)}
    cols = ["name", "exchange", "close", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.YTD", "Perf.Y"]
    data = post({"filter": [{"left": "name", "operation": "in_range", "right": list(shares)}],
                 "columns": cols, "range": [0, 500]})
    best = {}
    for r in data:
        d = dict(zip(cols, r["d"]))
        if d["name"] in shares and (d["name"] not in best or d["exchange"] in ("NASDAQ", "NYSE")):
            best[d["name"]] = d
    points = {}
    for label in ["Perf.Y", "Perf.6M", "Perf.YTD", "Perf.3M", "Perf.1M", "Perf.W"]:
        total = 0.0
        for t, d in best.items():
            perf = d.get(label)
            total += shares[t] * d["close"] / (1 + perf / 100) if perf is not None else shares[t] * d["close"]
        points[label.replace("Perf.", "")] = round(total, 2)
    points["now"] = round(sum(shares[t] * d["close"] for t, d in best.items()), 2)
    return {"points": points, "missing": [t for t in shares if t not in best]}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "screen"
    try:
        result = history(sys.argv[2:]) if mode == "history" else {"value": value_screen(), "momentum": momentum_screen()}
    except Exception as e:
        result = {"error": str(e)}
    print(json.dumps(result, indent=1))
