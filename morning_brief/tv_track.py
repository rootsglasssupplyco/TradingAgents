"""Daily price snapshot for tracked picks, from TradingView's scanner.

  python3 tv_track.py EXE VMI WCC ...   (SPY is always added as the benchmark)
  python3 tv_track.py lessons <picks_dir> <prices_dir>
      Reads picks/prices JSON files (as saved by ArtifactData with out_dir) and prints
      each pick's return, return vs SPY, sessions held, and which reflection milestone
      (5/20/60/120/250 sessions, or exit level hit) is due -- like the repo's memory log.

Prints one `prices` document for the dashboard:
  {"date": session date (US/Eastern), "generatedAt", "intraday": bool,
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


def session(now):
    """The trading session the scanner's numbers belong to (weekends/pre-open roll back)."""
    day = now.date()
    if now.weekday() >= 5 or now.time() < dt.time(9, 30):
        day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    open_now = now.weekday() < 5 and dt.time(9, 30) <= now.time() < dt.time(16, 0)
    return day.isoformat(), open_now


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
    date, intraday = session(now)
    prices = {}
    for t, d in best.items():
        chg = d.get("change")
        prev = round(d["close"] / (1 + chg / 100), 4) if chg is not None else None
        prices[t] = {k: d.get(k) for k in ("open", "high", "low", "close")}
        prices[t]["prevClose"] = prev
    return {"date": date, "generatedAt": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
            "intraday": intraday, "prices": prices, "missing": [t for t in tickers if t not in prices]}


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
    days = sorted(prices.values(), key=lambda d: d["date"])
    out = []
    for i, d in enumerate(days):
        p = (d.get("prices") or {}).get(ticker)
        if not p or p.get("close") is None:
            continue
        c = p["close"]
        for nxt in days[i + 1:]:
            q = (nxt.get("prices") or {}).get(ticker)
            if q:
                c = q.get("prevClose") or c
                break
        out.append((d["date"], c))
    return out


def lessons(picks_dir, prices_dir):
    picks, prices = load_dir(picks_dir), load_dir(prices_dir)
    spy = closes(prices, "SPY")
    rows = []
    for pid, pk in sorted(picks.items()):
        cs = [c for c in closes(prices, pk["ticker"]) if c[0] >= pk["recSession"]]
        ss = [c for c in spy if c[0] >= pk["recSession"]]
        if not cs:
            rows.append({"id": pid, "ticker": pk["ticker"], "sessions": 0})
            continue
        last = cs[-1][1]
        ret = (last / pk["recPrice"] - 1) * 100
        spy_ret = (ss[-1][1] / pk["spyAtRec"] - 1) * 100 if ss and pk.get("spyAtRec") else None
        sessions = len(cs) - 1
        done = {r.get("milestone") for r in pk.get("reflections") or []}
        exit_hit = pk.get("exitLevel") is not None and any(c < pk["exitLevel"] for _, c in cs[1:])
        due = [m for m in MILESTONES if sessions >= m and m not in done]
        if exit_hit and "exit" not in done:
            due.append("exit")
        rows.append({
            "id": pid, "ticker": pk["ticker"], "heat": pk.get("heat"), "setup": pk.get("setup"),
            "status": pk.get("status"), "bought": pk.get("bought"), "recDate": pk.get("recDate"),
            "sessions": sessions, "returnPct": round(ret, 2),
            "vsSpyPts": round(ret - spy_ret, 2) if spy_ret is not None else None,
            "peakPct": round((max(c for _, c in cs) / pk["recPrice"] - 1) * 100, 2),
            "troughPct": round((min(c for _, c in cs) / pk["recPrice"] - 1) * 100, 2),
            "exitHit": exit_hit, "reflectionDue": due[-1] if due else None,
            "pastReflections": [r.get("note") for r in (pk.get("reflections") or [])][-2:],
        })
    by = {}
    for r in rows:
        if r.get("vsSpyPts") is None:
            continue
        g = by.setdefault(f'{r["heat"]}-fire {r["setup"]}', [])
        g.append(r["vsSpyPts"])
    summary = {k: {"calls": len(v), "avgVsSpyPts": round(sum(v) / len(v), 2), "beatRate": round(sum(x > 0 for x in v) / len(v), 2)}
               for k, v in sorted(by.items())}
    return {"picks": rows, "byHeatAndSetup": summary}


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "lessons":
            print(json.dumps(lessons(sys.argv[2], sys.argv[3]), indent=1))
            sys.exit(0)
        print(json.dumps(main(sys.argv[1:]), indent=1))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
