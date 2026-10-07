"""Screen US stocks on TradingView for two buy setups, plus history for current holdings.

  python3 tv_screen.py screen               -> {"value": [...], "momentum": [...], "notes": [...]}
  python3 tv_screen.py history T=SHARES ...  -> past values of these holdings (1W..1Y ago)

value:    profitable, cash-generating, cheap on NEXT year's earnings (which must not be shrinking),
          analysts see 20%+ upside to the median target, and the price has stopped falling
          (back above a rising 50-day average). Avoids falling knives and peak-cycle earnings.
momentum: profitable company in a young uptrend: above rising 50/200-day averages but not
          stretched (1-year gain <= 60%, <= 25% above the 200-day), near its 52-week high on
          normal-or-better volume, not overbought, moderate volatility.
Results are candidates for research, not buy signals. Standard library only.
"""
import datetime as dt
import json
import sys
import urllib.request

URL = "https://scanner.tradingview.com/america/scan"
COLS = ["name", "description", "sector", "close", "change", "market_cap_basic", "Value.Traded",
        "price_earnings_ttm", "non_gaap_price_to_earnings_per_share_forecast_next_fy",
        "earnings_per_share_diluted_ttm", "earnings_per_share_forecast_next_fy",
        "earnings_per_share_diluted_yoy_growth_ttm", "total_revenue_yoy_growth_ttm",
        "net_income_ttm", "free_cash_flow_ttm", "return_on_invested_capital", "debt_to_equity",
        "price_target_median", "price_target_high", "price_target_low", "recommendation_mark",
        "recommendation_total", "SMA50", "SMA50[1]", "SMA200", "SMA200[1]", "RSI", "Perf.1M",
        "Perf.3M", "Perf.6M", "Perf.Y", "price_52_week_high", "relative_volume_10d_calc",
        "Volatility.M", "dividends_yield_current", "dividend_payout_ratio_ttm",
        "earnings_release_next_date", "beta_1_year"]
BASE = [
    {"left": "type", "operation": "equal", "right": "stock"},
    {"left": "is_primary", "operation": "equal", "right": True},
    {"left": "exchange", "operation": "in_range", "right": ["NASDAQ", "NYSE", "AMEX"]},
    {"left": "Value.Traded", "operation": "greater", "right": 2e7},  # liquid enough to trade
    {"left": "net_income_ttm", "operation": "greater", "right": 0},  # must make money
]
NOTES = []


def post(body):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rows(filters, n=800):
    res = post({"filter": BASE + filters, "columns": COLS, "range": [0, n],
                "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"}})
    if res.get("totalCount", 0) > n:
        NOTES.append(f"screen truncated: {res['totalCount']} matches, kept the largest {n}")
    return [dict(zip(COLS, r["d"])) for r in res.get("data", [])]


def r1(v):
    return round(v, 1) if isinstance(v, (int, float)) else None


def card(d, setup, score):
    close, target = d["close"], d.get("price_target_median")
    ed = d.get("earnings_release_next_date")
    hi, lo = d.get("price_target_high"), d.get("price_target_low")
    return {
        "setup": setup, "ticker": d["name"], "name": d["description"], "sector": d["sector"],
        "price": close, "upsidePct": r1((target / close - 1) * 100) if target and close else None,
        "targetSpreadPct": r1((hi - lo) / close * 100) if hi and lo and close else None,
        "analystMark": r1(d.get("recommendation_mark")), "analysts": d.get("recommendation_total"),
        "pe": r1(d.get("price_earnings_ttm")),
        "fwdPe": r1(d.get("non_gaap_price_to_earnings_per_share_forecast_next_fy")),
        "epsTtm": r1(d.get("earnings_per_share_diluted_ttm")),
        "epsNextFy": r1(d.get("earnings_per_share_forecast_next_fy")),
        "revGrowth": r1(d.get("total_revenue_yoy_growth_ttm")),
        "roic": r1(d.get("return_on_invested_capital")), "fcfPositive": (d.get("free_cash_flow_ttm") or 0) > 0,
        "rsi": r1(d.get("RSI")), "perf1M": r1(d.get("Perf.1M")), "perf3M": r1(d.get("Perf.3M")),
        "perf6M": r1(d.get("Perf.6M")), "perfY": r1(d.get("Perf.Y")),
        "sma50": r1(d.get("SMA50")), "sma200": r1(d.get("SMA200")), "high52": d.get("price_52_week_high"),
        "relVolume": r1(d.get("relative_volume_10d_calc")), "volatilityM": r1(d.get("Volatility.M")),
        "beta": r1(d.get("beta_1_year")),
        "dividendYield": r1(d.get("dividends_yield_current")), "payoutRatio": r1(d.get("dividend_payout_ratio_ttm")),
        "nextEarnings": dt.datetime.fromtimestamp(ed, dt.timezone.utc).date().isoformat() if ed else None,
        "marketCapB": r1(d["market_cap_basic"] / 1e9), "score": round(score, 2),
    }


def dividend_tilt(d):
    y, pr = d.get("dividends_yield_current") or 0, d.get("dividend_payout_ratio_ttm")
    return min(y, 4) / 8 if y and pr is not None and pr < 70 else 0  # up to +0.5 for a covered dividend


def value_screen():
    out = []
    for d in rows([
        {"left": "market_cap_basic", "operation": "greater", "right": 5e9},
        {"left": "non_gaap_price_to_earnings_per_share_forecast_next_fy", "operation": "in_range", "right": [3, 20]},
        {"left": "recommendation_mark", "operation": "less", "right": 2},
        {"left": "recommendation_total", "operation": "greater", "right": 7},
        {"left": "free_cash_flow_ttm", "operation": "greater", "right": 0},
        {"left": "close", "operation": "greater", "right": "SMA50"},
    ]):
        close, target = d["close"], d.get("price_target_median")
        eps, eps_next = d.get("earnings_per_share_diluted_ttm"), d.get("earnings_per_share_forecast_next_fy")
        if not (close and target and d.get("SMA200") and eps and eps_next):
            continue
        upside = target / close - 1
        if upside < 0.20 or close > d["SMA200"] * 1.10:
            continue  # not enough upside, or already well above its long-term trend
        if eps_next < eps:
            continue  # earnings expected to shrink: likely peak-cycle "cheap"
        if (d.get("SMA50[1]") or 0) > d["SMA50"] or (d.get("Perf.6M") or 0) < -15:
            continue  # 50-day still falling, or a deep slide: not stabilized yet
        if (d.get("return_on_invested_capital") or 0) < 8:
            continue
        if d["sector"] != "Finance" and (d.get("debt_to_equity") is None or d["debt_to_equity"] > 1.5):
            continue
        growth = min(max((eps_next / eps - 1) * 100, 0), 50)
        spread = ((d.get("price_target_high") or target) - (d.get("price_target_low") or target)) / close
        score = min(upside, 0.5) * 2 + growth / 50 + (2 - d["recommendation_mark"]) - min(spread, 1) * 0.5 + dividend_tilt(d)
        out.append(card(d, "Value", score))
    return sorted(out, key=lambda c: -c["score"])[:10]


def momentum_screen():
    out = []
    for d in rows([
        {"left": "market_cap_basic", "operation": "greater", "right": 2e9},
        {"left": "earnings_per_share_diluted_ttm", "operation": "greater", "right": 0},
        {"left": "close", "operation": "greater", "right": "SMA50"},
        {"left": "SMA50", "operation": "greater", "right": "SMA200"},
        {"left": "RSI", "operation": "in_range", "right": [55, 70]},
        {"left": "Perf.6M", "operation": "in_range", "right": [10, 40]},
        {"left": "Perf.Y", "operation": "less", "right": 60},
        {"left": "total_revenue_yoy_growth_ttm", "operation": "greater", "right": 10},
    ]):
        sma50, sma200, high = d["SMA50"], d["SMA200"], d.get("price_52_week_high")
        relvol, vol = d.get("relative_volume_10d_calc") or 0, d.get("Volatility.M") or 99
        if not (high and sma200) or d["close"] > sma200 * 1.25 or sma50 / sma200 > 1.12:
            continue  # stretched or mature trend
        if d["close"] < high * 0.92 or relvol < 0.9 or vol >= 4:
            continue  # not near a breakout, no volume behind it, or too jumpy
        if (d.get("SMA50[1]") or sma50) > sma50 or (d.get("SMA200[1]") or sma200) > sma200:
            continue  # averages must be rising
        fresh = 1.12 - sma50 / sma200  # bigger when the 50-day crossed the 200-day recently
        hot_month = max((d.get("Perf.1M") or 0) - 15, 0) / 10  # short-term spikes tend to fade
        score = (d["Perf.6M"] / 10) + fresh * 15 + min(relvol, 2) - hot_month + dividend_tilt(d)
        out.append(card(d, "Early momentum", score))
    return sorted(out, key=lambda c: -c["score"])[:10]


def history(pairs):
    shares = {t.upper(): float(s) for t, s in (p.split("=") for p in pairs)}
    cols = ["name", "exchange", "close", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.YTD", "Perf.Y"]
    data = post({"filter": [{"left": "name", "operation": "in_range", "right": list(shares)}],
                 "columns": cols, "range": [0, 500]}).get("data", [])
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
        if mode == "history":
            result = history(sys.argv[2:])
        else:
            result = {"value": value_screen(), "momentum": momentum_screen(), "notes": NOTES}
    except Exception as e:
        result = {"error": str(e)}
    print(json.dumps(result, indent=1))
