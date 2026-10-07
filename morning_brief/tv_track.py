"""Daily price snapshot for tracked picks, from TradingView's scanner.

  python3 tv_track.py EXE VMI WCC ...   (SPY is always added as the benchmark)
  python3 tv_track.py session
      Today's session facts: {date, prevSession, intraday, holiday, earlyClose}.
  python3 tv_track.py validate <brief.json> <lessons.json> [--portfolio VALUE]
      Checks a brief before it is written against the rules and the ledger from `lessons`.
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
EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-07-02", "2027-11-26"}  # 1:00 PM ET close
HOLIDAYS_THROUGH = 2027


def is_trading_day(day):
    return day.weekday() < 5 and day.isoformat() not in HOLIDAYS


def last_session_of_week(day):
    """True when no later trading day falls in the same Monday-Sunday week (Friday, or Thursday before a Friday holiday)."""
    nxt = day + dt.timedelta(days=1)
    while not is_trading_day(nxt):
        nxt += dt.timedelta(days=1)
    return nxt.isocalendar()[1] != day.isocalendar()[1]


def prev_trading_day(day):
    day -= dt.timedelta(days=1)
    while not is_trading_day(day):
        day -= dt.timedelta(days=1)
    return day


def session(now):
    """The trading session the scanner's numbers belong to (weekends, holidays, pre-open roll back)."""
    today = now.date()
    if today.year > HOLIDAYS_THROUGH:
        raise RuntimeError(f"HOLIDAYS list ends in {HOLIDAYS_THROUGH}; add {today.year}'s NYSE holidays to tv_track.py")
    close_t = dt.time(13, 0) if today.isoformat() in EARLY_CLOSE else dt.time(16, 0)
    open_now = is_trading_day(today) and dt.time(9, 30) <= now.time() < close_t
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
BASE_AMOUNT = {5: 500, 4: 350, 3: 200, 2: 100, 1: 50}


def add_trading_days(day_iso, n):
    d = dt.date.fromisoformat(day_iso)
    while n > 0:
        d += dt.timedelta(days=1)
        if is_trading_day(d):
            n -= 1
    return d.isoformat()


def exit_level_on(pk, date):
    """Exit level in force on `date`; exitHistory [{from, level}] records raises over time."""
    hist = sorted(pk.get("exitHistory") or [], key=lambda h: h["from"])
    level = pk.get("exitLevel") if not hist else None
    for h in hist:
        if h["from"] <= date:
            level = h["level"]
    return level


def today_et():
    return dt.datetime.now(ZoneInfo("America/New_York")).date()


def lessons(picks_dir, prices_dir):
    picks, prices = load_dir(picks_dir), load_dir(prices_dir)
    spy = closes(prices, "SPY")
    latest = max((d["date"] for d in prices.values()), default=None)
    rows = []
    for pid, pk in sorted(picks.items()):
        if pk.get("status") not in ("open", "closed"):
            continue  # withdrawn or other non-live calls are not scored
        year_end = (dt.date.fromisoformat(pk["recDate"]) + dt.timedelta(days=365)).isoformat()
        closed = pk.get("status") == "closed" and pk.get("closeDate")
        cs = [c for c in closes(prices, pk["ticker"]) if pk["recSession"] <= c[0] <= year_end]
        if closed:
            cs = [c for c in cs if c[0] <= pk["closeDate"]]
        if not cs or not pk.get("recPrice"):
            rows.append({"id": pid, "ticker": pk["ticker"], "sessions": 0})
            continue
        last = pk["closePrice"] if closed and pk.get("closePrice") else cs[-1][1]
        ret = (last / pk["recPrice"] - 1) * 100
        spy_end = at_or_before(spy, cs[-1][0])
        spy_ret = (spy_end / pk["spyAtRec"] - 1) * 100 if spy_end and pk.get("spyAtRec") else None
        horizon = {}
        for h in HORIZONS:
            target = add_trading_days(pk["recSession"], h)
            if target > year_end or not latest or target > latest:
                continue  # horizon not reached yet
            if closed and pk["closeDate"] <= target and pk.get("closePrice"):
                px = pk["closePrice"]  # sold: hold the cash flat to the horizon
            else:
                px = at_or_before(cs, target)
            s = at_or_before(spy, target)
            if px and s and pk.get("spyAtRec"):
                horizon[h] = round((px / pk["recPrice"] - 1) * 100 - (s / pk["spyAtRec"] - 1) * 100, 2)
        finals = [c for c in cs[1:] if c[2]]
        first_exit = next((c for c in finals if (lvl := exit_level_on(pk, c[0])) is not None and c[1] < lvl), None)
        done = {r.get("milestone") for r in pk.get("reflections") or []}
        sessions = sum(1 for c in cs[1:])
        due = [m for m in (5,) + HORIZONS if m in horizon or (m == 5 and sessions >= 5) if m not in done]
        if first_exit and "exit" not in done:
            due.append("exit")
        rows.append({
            "id": pid, "ticker": pk["ticker"], "heat": pk.get("heat"), "setup": pk.get("setup"),
            "status": pk.get("status"), "bought": pk.get("bought"), "recDate": pk.get("recDate"),
            "amount": pk.get("amount"), "overBudget": pk.get("overBudget") or 0,
            "sessions": sessions, "returnPct": round(ret, 2),
            "vsSpyPts": round(ret - spy_ret, 2) if spy_ret is not None else None,
            "vsSpyAtHorizon": horizon,
            "peakPct": round((max(c[1] for c in cs) / pk["recPrice"] - 1) * 100, 2),
            "troughPct": round((min(c[1] for c in cs) / pk["recPrice"] - 1) * 100, 2),
            "exitHit": bool(first_exit),
            "returnIfExitFollowedPct": round((first_exit[1] / pk["recPrice"] - 1) * 100, 2) if first_exit else None,
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
    today = today_et()
    week_start = (today - dt.timedelta(days=today.weekday())).isoformat()  # Monday
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    live = [pk for pk in picks.values() if pk.get("status") in ("open", "closed")]
    this_week = [pk for pk in live if pk.get("recDate", "") >= week_start]
    ledger = {
        "weekOf": week_start,
        "stockSpentThisWeek": round(sum(pk.get("amount") or 0 for pk in this_week), 2),
        "overBudgetThisWeek": round(sum(pk.get("overBudget") or 0 for pk in this_week), 2),
        "openMomentum": sum(1 for pk in live if pk.get("status") == "open" and pk.get("setup") == "Early momentum"),
        "picksLast7Days": sum(1 for pk in live if pk.get("recDate", "") > week_ago),
        "openTickers": sorted({pk["ticker"] for pk in live if pk.get("status") == "open"}),
    }
    scored = sum(1 for r in rows if (r.get("vsSpyAtHorizon") or {}).get(20) is not None)
    return {"ledger": ledger, "picks": rows, "vsSpyByHorizon": summary, "scoredAt20Sessions": scored,
            "enoughToChangeRules": scored >= 30,
            "note": "Price returns only (dividends excluded). Horizons count trading days from the call; sold picks hold cash flat. Compare groups only at the same horizon."}


REQUIRED = ["date", "generatedAt", "isLastSessionOfWeek", "marketSummary", "lessons", "indices", "portfolio", "weeklyPlan",
            "recommendations", "quotes", "news", "disclaimer"]
WEEKLY_BUDGET, INDEX_MIN, STOCK_ALLOWANCE = 500.0, 300.0, 200.0
HOT_MAX = {4: 400.0, 5: 600.0}  # a 4-5 fire deal may go over the weekly $500, up to this much
# The broker (Vanguard) sells fractional shares only of Vanguard funds; everything else is whole shares.
VANGUARD = {"VOO", "VTI", "VXUS", "VEA", "VWO", "VTV", "VUG", "VOOG", "VOOV", "VHT", "VGT", "VIG", "VYM", "VNQ",
            "BND", "BNDX", "VB", "VBR", "VO", "VXF", "VT", "VDC", "VPU", "VDE", "VFH", "VIS", "VAW", "VCR", "VOX", "MGK", "MGV"}


def whole_share_check(t, amount, shares, price, errors):
    if not isinstance(shares, int) or shares < 1:
        errors.append(f"{t}: not a Vanguard fund, so give a whole number of `shares` (at least 1)")
    elif price and amount and abs(shares * price - amount) > max(0.03 * amount, 2):
        errors.append(f"{t}: amount ${amount:.2f} should be shares x price ({shares} x ${price:.2f} = ${shares * price:.2f})")


def validate(brief_path, lessons_path, portfolio=None):
    with open(brief_path) as f:
        b = json.load(f)
    with open(lessons_path) as f:
        ledger = json.load(f)["ledger"]
    errors, warnings = [], []
    for k in REQUIRED:
        if k not in b:
            errors.append(f"missing key: {k}")
    recs = b.get("recommendations", [])
    buys = [r for r in recs if r.get("action") in ("BUY", "ADD")]
    for r in recs:
        t = r.get("ticker", "?")
        if r.get("action") not in ("BUY", "ADD"):
            continue
        heat = r.get("heat")
        if not isinstance(heat, int) or not 1 <= heat <= 5:
            errors.append(f"{t}: BUY/ADD needs heat 1-5")
            continue
        if r.get("setup") not in ("Value", "Early momentum"):
            errors.append(f"{t}: BUY/ADD setup must be Value or Early momentum (funds go in weeklyPlan)")
        if r.get("setup") == "Early momentum" and heat > 4:
            errors.append(f"{t}: momentum-only setups cap at 4 fires")
        if not r.get("exitPlan"):
            errors.append(f"{t}: missing exitPlan")
        if r.get("setup") == "Early momentum" and r.get("exitLevel") is None:
            errors.append(f"{t}: momentum buys need a numeric exitLevel")
        elif r.get("exitLevel") is None:
            warnings.append(f"{t}: no numeric exitLevel; say why in exitPlan")
        amt = r.get("amount") or 0
        whole_share_check(t, amt, r.get("shares"), r.get("price"), errors)
        cap = HOT_MAX.get(heat, BASE_AMOUNT[heat] * 1.25)
        if not amt:
            errors.append(f"{t}: missing amount")
        elif amt > cap:
            errors.append(f"{t}: ${amt:.0f} is above the {heat}-fire limit (${cap:.0f})")
        if portfolio and amt > 0.03 * portfolio:
            errors.append(f"{t}: ${amt:.0f} is over 3% of the portfolio (${0.03 * portfolio:.0f})")
        if (r.get("overBudget") or 0) > 0 and heat < 4:
            errors.append(f"{t}: only 4-5 fire deals may go over the weekly budget")
        if not (r.get("debate") or {}).get("bear"):
            warnings.append(f"{t}: no bear case recorded")
        if t in ledger.get("openTickers", []):
            warnings.append(f"{t}: already has an open pick; explain why this is a new, stronger entry")
    allowance_left = max(STOCK_ALLOWANCE - ledger["stockSpentThisWeek"] + ledger.get("overBudgetThisWeek", 0), 0)
    regular = sum((r.get("amount") or 0) - (r.get("overBudget") or 0) for r in buys)
    if regular > allowance_left + 0.01:
        errors.append(f"stock buys use ${regular:.0f} of this week's ${STOCK_ALLOWANCE:.0f} stock allowance but only "
                      f"${allowance_left:.0f} is left; mark the extra as overBudget (4-5 fire only) or shrink it")
    wp = b.get("weeklyPlan") or {}
    index_total = sum(i.get("amount") or 0 for i in wp.get("items", []) if i.get("kind") == "index")
    for i in wp.get("items", []):
        if i.get("kind") == "index" and i.get("ticker") not in VANGUARD:
            whole_share_check(i.get("ticker", "?"), i.get("amount") or 0, i.get("shares"), i.get("price"), errors)
    if b.get("weeklyRecap") is None and b.get("isLastSessionOfWeek"):
        errors.append("last session of the week: add weeklyRecap")
    if wp and index_total + 0.01 < INDEX_MIN:
        errors.append(f"weeklyPlan puts ${index_total:.0f} in index funds; the minimum is ${INDEX_MIN:.0f}")
    over = sum(r.get("overBudget") or 0 for r in buys)
    if over and not wp.get("overBudget"):
        warnings.append(f"weeklyPlan.overBudget should show the ${over:.0f} extra so the investor sees it")
    new_mom = sum(1 for r in buys if r.get("setup") == "Early momentum" and r.get("ticker") not in ledger.get("openTickers", []))
    if ledger["openMomentum"] + new_mom > 2:
        errors.append(f"would make {ledger['openMomentum'] + new_mom} open momentum picks (max 2)")
    if ledger["picksLast7Days"] + len(buys) > 2:
        errors.append(f"would make {ledger['picksLast7Days'] + len(buys)} new picks in 7 days (max 2)")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stockAllowanceLeft": allowance_left,
            "stockRegular": regular, "overBudget": over, "indexTotal": index_total}


if __name__ == "__main__":
    try:
        arg = lambda name, default=None: float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
        if len(sys.argv) > 1 and sys.argv[1] == "session":
            now = dt.datetime.now(ZoneInfo("America/New_York"))
            date, prev, intraday, holiday = session(now)
            print(json.dumps({"date": date, "prevSession": prev, "intraday": intraday, "holiday": holiday,
                              "earlyClose": now.date().isoformat() in EARLY_CLOSE,
                              "lastSessionOfWeek": last_session_of_week(dt.date.fromisoformat(date))}))
            sys.exit(0)
        if len(sys.argv) > 1 and sys.argv[1] == "validate":
            print(json.dumps(validate(sys.argv[2], sys.argv[3], arg("--portfolio")), indent=1))
            sys.exit(0)
        if len(sys.argv) > 1 and sys.argv[1] == "lessons":
            print(json.dumps(lessons(sys.argv[2], sys.argv[3]), indent=1))
            sys.exit(0)
        print(json.dumps(main(sys.argv[1:]), indent=1))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
