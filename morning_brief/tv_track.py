"""Daily price snapshot for tracked picks, from TradingView's scanner.

  python3 tv_track.py EXE VMI WCC ...   (SPY is always added as the benchmark)
  python3 tv_track.py validate <brief.json> [--spent N]
      Checks a brief before it is written: required keys, fires 1-5, every BUY/ADD has an
      exitPlan and an exitLevel or a stated reason, buys fit the month's remaining budget.
  python3 tv_track.py lessons <picks_dir> <prices_dir>
      Reads picks/prices JSON files (as saved by ArtifactData with out_dir) and prints
      each pick's return, return vs SPY, sessions held, and which reflection milestone
      (5/20/60/120/250 sessions, or exit level hit) is due -- like the repo's memory log.

Prints one `prices` document for the dashboard:
  {"date": session date (US/Eastern), "prevSession", "generatedAt", "intraday": bool, "holiday": bool,
   "prices": {TICKER: {"open", "high", "low", "close", "prevClose"}}}
`close` is the latest price (intraday before 4pm ET); `prevClose` is the prior
session's final close, which the dashboard uses to finalize yesterday's candle.
Standard library only.
"""
import datetime as dt
import json
import sys
import urllib.request
from zoneinfo import ZoneInfo

URL = "https://scanner.tradingview.com/america/scan"
COLS = ["name", "exchange", "open", "high", "low", "close", "change"]
RANK = {"NASDAQ": 0, "NYSE": 0, "AMEX": 1}


# NYSE full-day closures. Extend each year.
HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
}


def is_trading_day(day):
    return day.weekday() < 5 and day.isoformat() not in HOLIDAYS


def prev_trading_day(day):
    day -= dt.timedelta(days=1)
    while not is_trading_day(day):
        day -= dt.timedelta(days=1)
    return day


def session(now):
    """The trading session the scanner's numbers belong to (weekends, holidays, pre-open roll back)."""
    today = now.date()
    open_now = is_trading_day(today) and dt.time(9, 30) <= now.time() < dt.time(16, 0)
    day = today if is_trading_day(today) and now.time() >= dt.time(9, 30) else prev_trading_day(today)
    return day.isoformat(), prev_trading_day(day).isoformat(), open_now, not is_trading_day(today)


def main(tickers):
    tickers = sorted({t.upper() for t in tickers} | {"SPY"})
    body = {"filter": [{"left": "name", "operation": "in_range", "right": tickers}], "columns": COLS, "range": [0, 500]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = [dict(zip(COLS, x["d"])) for x in json.load(r).get("data", [])]
    best = {}
    for d in rows:
        if d["name"] in tickers and d.get("close") is not None:
            if d["name"] not in best or RANK.get(d["exchange"], 9) < RANK.get(best[d["name"]]["exchange"], 9):
                best[d["name"]] = d
    now = dt.datetime.now(ZoneInfo("America/New_York"))
    date, prev_session, intraday, holiday = session(now)
    prices = {}
    for t, d in best.items():
        chg = d.get("change")
        prev = round(d["close"] / (1 + chg / 100), 4) if chg is not None else None
        prices[t] = {k: d.get(k) for k in ("open", "high", "low", "close")}
        prices[t]["prevClose"] = prev
    return {"date": date, "prevSession": prev_session, "generatedAt": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
            "intraday": intraday, "holiday": holiday, "prices": prices, "missing": [t for t in tickers if t not in prices]}


MILESTONES = (5, 20, 60, 120, 250)


def load_dir(path):
    import glob
    import os
    out = {}
    for f in glob.glob(os.path.join(path, "*.json")):
        with open(f) as fh:
            d = json.load(fh)
        out[os.path.splitext(os.path.basename(f))[0]] = d
    return out


def closes(prices, ticker):
    """[(date, close, final)] -- a close is final once the next session's snapshot supplies prevClose."""
    days = sorted(prices.values(), key=lambda d: d["date"])
    by_prev = {d.get("prevSession"): d for d in days if d.get("prevSession")}
    out = []
    for i, d in enumerate(days):
        p = (d.get("prices") or {}).get(ticker)
        if not p or p.get("close") is None:
            continue
        nxt = by_prev.get(d["date"])
        if nxt is None and i + 1 < len(days) and not days[i + 1].get("prevSession"):
            nxt = days[i + 1]  # older snapshots without prevSession: assume consecutive
        q = (nxt.get("prices") or {}).get(ticker) if nxt else None
        if q and q.get("prevClose") is not None:
            out.append((d["date"], q["prevClose"], True))
        else:
            out.append((d["date"], p["close"], not d.get("intraday", False)))
    return out


def at_or_before(series, date):
    v = None
    for d, c, *_ in series:
        if d <= date:
            v = c
        else:
            break
    return v


HORIZONS = (20, 60, 120, 250)


def lessons(picks_dir, prices_dir):
    picks, prices = load_dir(picks_dir), load_dir(prices_dir)
    spy = closes(prices, "SPY")
    rows = []
    for pid, pk in sorted(picks.items()):
        cs = [c for c in closes(prices, pk["ticker"]) if c[0] >= pk["recSession"]]
        if pk.get("status") == "closed" and pk.get("closeDate"):
            cs = [c for c in cs if c[0] <= pk["closeDate"]]
        if not cs or not pk.get("recPrice"):
            rows.append({"id": pid, "ticker": pk["ticker"], "sessions": 0})
            continue
        last = pk["closePrice"] if pk.get("status") == "closed" and pk.get("closePrice") else cs[-1][1]
        end = cs[-1][0]
        ret = (last / pk["recPrice"] - 1) * 100
        spy_end = at_or_before(spy, end)
        spy_ret = (spy_end / pk["spyAtRec"] - 1) * 100 if spy_end and pk.get("spyAtRec") else None
        sessions = len(cs) - 1
        horizon = {}
        for h in HORIZONS:
            if sessions >= h:
                d, c = cs[h][0], cs[h][1]
                s = at_or_before(spy, d)
                horizon[h] = round((c / pk["recPrice"] - 1) * 100 - ((s / pk["spyAtRec"] - 1) * 100 if s else 0), 2)
        finals = [c for c in cs[1:] if c[2]]
        exit_hit = pk.get("exitLevel") is not None and any(c[1] < pk["exitLevel"] for c in finals)
        exit_ret = None
        if exit_hit:
            first = next(c for c in finals if c[1] < pk["exitLevel"])
            exit_ret = round((first[1] / pk["recPrice"] - 1) * 100, 2)
        done = {r.get("milestone") for r in pk.get("reflections") or []}
        due = [m for m in (5,) + HORIZONS if sessions >= m and m not in done]
        if exit_hit and "exit" not in done:
            due.append("exit")
        rows.append({
            "id": pid, "ticker": pk["ticker"], "heat": pk.get("heat"), "setup": pk.get("setup"),
            "status": pk.get("status"), "bought": pk.get("bought"), "recDate": pk.get("recDate"),
            "sessions": sessions, "returnPct": round(ret, 2),
            "vsSpyPts": round(ret - spy_ret, 2) if spy_ret is not None else None,
            "vsSpyAtHorizon": horizon,
            "peakPct": round((max(c[1] for c in cs) / pk["recPrice"] - 1) * 100, 2),
            "troughPct": round((min(c[1] for c in cs) / pk["recPrice"] - 1) * 100, 2),
            "exitHit": exit_hit, "returnIfExitFollowedPct": exit_ret,
            "reflectionDue": due[-1] if due else None,
            "pastReflections": [r.get("note") for r in (pk.get("reflections") or [])][-2:],
        })
    summary = {}
    for h in HORIZONS:
        groups = {}
        for r in rows:
            v = (r.get("vsSpyAtHorizon") or {}).get(h)
            if v is not None:
                groups.setdefault(f'{r["heat"]}-fire {r["setup"]}', []).append(v)
        if groups:
            summary[f"{h} sessions"] = {k: {"calls": len(v), "avgVsSpyPts": round(sum(v) / len(v), 2),
                                            "beatRate": round(sum(x > 0 for x in v) / len(v), 2)} for k, v in sorted(groups.items())}
    scored = sum(1 for r in rows if (r.get("vsSpyAtHorizon") or {}).get(20) is not None)
    return {"picks": rows, "vsSpyByHorizon": summary, "scoredAt20Sessions": scored,
            "enoughToChangeRules": scored >= 30,
            "note": "Price returns only (dividends excluded). Compare groups only at the same horizon."}


REQUIRED = ["date", "generatedAt", "marketSummary", "indices", "portfolio", "monthlyPlan", "recommendations", "quotes", "news", "disclaimer"]


def validate(path, spent=0.0, budget=500.0, reserve=750.0):
    with open(path) as f:
        b = json.load(f)
    errors, warnings = [], []
    for k in REQUIRED:
        if k not in b:
            errors.append(f"missing key: {k}")
    buys = [r for r in b.get("recommendations", []) if r.get("action") in ("BUY", "ADD")]
    for r in b.get("recommendations", []):
        t = r.get("ticker", "?")
        if r.get("action") in ("BUY", "ADD"):
            if not isinstance(r.get("heat"), int) or not 1 <= r["heat"] <= 5:
                errors.append(f"{t}: BUY/ADD needs heat 1-5")
            if r.get("setup") not in ("Value", "Early momentum"):
                errors.append(f"{t}: BUY/ADD setup must be Value or Early momentum")
            if not r.get("exitPlan"):
                errors.append(f"{t}: missing exitPlan")
            if r.get("exitLevel") is None:
                warnings.append(f"{t}: no numeric exitLevel; say why in exitPlan")
            if r.get("setup") == "Early momentum" and r.get("exitLevel") is None:
                errors.append(f"{t}: momentum buys need a numeric exitLevel")
            if not r.get("amount"):
                errors.append(f"{t}: missing amount")
            if not (r.get("debate") or {}).get("bear"):
                warnings.append(f"{t}: no bear case recorded")
    total = sum(r.get("amount") or 0 for r in buys)
    remaining = max(budget - spent, 0)
    big = any((r.get("heat") or 0) >= 4 for r in buys)
    if total > remaining + (reserve if big else 0):
        errors.append(f"buys total ${total:.0f} but only ${remaining:.0f} of this month's ${budget:.0f} is left"
                      + (f" (+${reserve:.0f} SGOV reserve for 4-5 fire deals)" if big else ""))
    if len([r for r in buys if r.get("setup") == "Early momentum"]) > 2:
        errors.append("more than 2 momentum buys")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "buysTotal": total, "remainingBefore": remaining}


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "validate":
            spent = float(sys.argv[sys.argv.index("--spent") + 1]) if "--spent" in sys.argv else 0.0
            print(json.dumps(validate(sys.argv[2], spent), indent=1))
            sys.exit(0)
        if len(sys.argv) > 1 and sys.argv[1] == "lessons":
            print(json.dumps(lessons(sys.argv[2], sys.argv[3]), indent=1))
            sys.exit(0)
        print(json.dumps(main(sys.argv[1:]), indent=1))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
