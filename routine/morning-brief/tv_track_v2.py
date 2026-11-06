import datetime as dt
import json
import sys
import urllib.request
from zoneinfo import ZoneInfo
URL = 'https://scanner.tradingview.com/america/scan'
COLS = ['name', 'exchange', 'open', 'high', 'low', 'close', 'change']
RANK = {'NASDAQ': 0, 'NYSE': 0, 'AMEX': 1}
HOLIDAYS = {'2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24'}
EARLY_CLOSE = {'2026-11-27', '2026-12-24', '2027-07-02', '2027-11-26'}
HOLIDAYS_THROUGH = 2027

def is_trading_day(day):
    return day.weekday() < 5 and day.isoformat() not in HOLIDAYS

def last_session_of_week(day):
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
    today = now.date()
    if today.year > HOLIDAYS_THROUGH:
        raise RuntimeError(f"HOLIDAYS list ends in {HOLIDAYS_THROUGH}; add {today.year}'s NYSE holidays to tv_track.py")
    close_t = dt.time(13, 0) if today.isoformat() in EARLY_CLOSE else dt.time(16, 0)
    open_now = is_trading_day(today) and dt.time(9, 30) <= now.time() < close_t
    day = today if is_trading_day(today) and now.time() >= dt.time(9, 30) else prev_trading_day(today)
    return (day.isoformat(), prev_trading_day(day).isoformat(), open_now, not is_trading_day(today))

PAPER_TOP = 10
PAPER_SESSIONS = 60
PAPER_MAX = 300

def screen_ranks(screens, top):
    """{date: [(setup, rank, ticker, price)]} for the top-N candidates per setup in each screens/<date> doc."""
    out = {}
    for key, s in screens.items():
        date = s.get('date') or key
        rows = []
        for setup in ('value', 'momentum'):
            for i, c in enumerate((s.get(setup) or [])[:top]):
                if c.get('ticker'):
                    rows.append((c.get('setup') or setup, i + 1, c['ticker'].upper(), c.get('price')))
        out[date] = rows
    return out

def paper_tickers(screens_dir, today, top=PAPER_TOP):
    """Screen candidates still inside their PAPER_SESSIONS window, so later runs can price them."""
    import os
    if not screens_dir or not os.path.isdir(screens_dir):
        return []
    keep = set()
    for date, rows in screen_ranks(load_dir(screens_dir), top).items():
        if date <= today and add_trading_days(date, PAPER_SESSIONS + 1) >= today:
            keep.update(t for _, _, t, _ in rows)
    return sorted(keep)[:PAPER_MAX]

def main(tickers, screens_dir=None, top=PAPER_TOP):
    now = dt.datetime.now(ZoneInfo('America/New_York'))
    date, prev_session, intraday, holiday = session(now)
    tickers = sorted({t.upper() for t in tickers} | {'SPY'})
    paper = [t for t in paper_tickers(screens_dir, date, top) if t not in tickers]
    want = tickers + paper
    body = {'filter': [{'left': 'name', 'operation': 'in_range', 'right': want}], 'columns': COLS, 'range': [0, 1500]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = [dict(zip(COLS, x['d'])) for x in json.load(r).get('data', [])]
    best = {}
    for d in rows:
        if d['name'] in want and d.get('close') is not None:
            if d['name'] not in best or RANK.get(d['exchange'], 9) < RANK.get(best[d['name']]['exchange'], 9):
                best[d['name']] = d
    prices, paper_px = ({}, {})
    for t, d in best.items():
        chg = d.get('change')
        prev = round(d['close'] / (1 + chg / 100), 4) if chg is not None else None
        if t in tickers:
            prices[t] = {k: d.get(k) for k in ('open', 'high', 'low', 'close')}
            prices[t]['prevClose'] = prev
        else:
            paper_px[t] = {'close': d.get('close'), 'prevClose': prev}
    out = {'date': date, 'prevSession': prev_session, 'generatedAt': now.astimezone(dt.timezone.utc).isoformat(timespec='seconds'), 'intraday': intraday, 'holiday': holiday, 'prices': prices, 'missing': [t for t in tickers if t not in prices]}
    if screens_dir:
        out['paper'] = paper_px
        out['missing'] += [t for t in paper if t not in paper_px]
    return out
MILESTONES = (5, 20, 60, 120, 250)

def load_dir(path):
    import glob
    import os
    out = {}
    for f in glob.glob(os.path.join(path, '*.json')):
        with open(f) as fh:
            d = json.load(fh)
        out[os.path.splitext(os.path.basename(f))[0]] = d
    return out

def closes(prices, ticker):
    days = sorted(prices.values(), key=lambda d: d['date'])
    by_prev = {d.get('prevSession'): d for d in days if d.get('prevSession')}
    out = []
    for i, d in enumerate(days):
        p = (d.get('prices') or {}).get(ticker)
        if not p or p.get('close') is None:
            continue
        nxt = by_prev.get(d['date'])
        if nxt is None and i + 1 < len(days) and (not days[i + 1].get('prevSession')):
            nxt = days[i + 1]
        q = (nxt.get('prices') or {}).get(ticker) if nxt else None
        if q and q.get('prevClose') is not None:
            out.append((d['date'], q['prevClose'], True))
        else:
            out.append((d['date'], p['close'], not d.get('intraday', False)))
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
    hist = sorted(pk.get('exitHistory') or [], key=lambda h: h['from'])
    level = pk.get('exitLevel') if not hist else None
    for h in hist:
        if h['from'] <= date:
            level = h['level']
    return level

def today_et():
    return dt.datetime.now(ZoneInfo('America/New_York')).date()

def lessons(picks_dir, prices_dir):
    picks, prices = (load_dir(picks_dir), load_dir(prices_dir))
    spy = closes(prices, 'SPY')
    latest = max((d['date'] for d in prices.values()), default=None)
    rows = []
    for pid, pk in sorted(picks.items()):
        if pk.get('status') not in ('open', 'closed'):
            continue
        year_end = (dt.date.fromisoformat(pk['recDate']) + dt.timedelta(days=365)).isoformat()
        closed = pk.get('status') == 'closed' and pk.get('closeDate')
        cs = [c for c in closes(prices, pk['ticker']) if pk['recSession'] <= c[0] <= year_end]
        if closed:
            cs = [c for c in cs if c[0] <= pk['closeDate']]
        if not cs or not pk.get('recPrice'):
            rows.append({'id': pid, 'ticker': pk['ticker'], 'sessions': 0})
            continue
        last = pk['closePrice'] if closed and pk.get('closePrice') else cs[-1][1]
        ret = (last / pk['recPrice'] - 1) * 100
        spy_end = at_or_before(spy, cs[-1][0])
        spy_ret = (spy_end / pk['spyAtRec'] - 1) * 100 if spy_end and pk.get('spyAtRec') else None
        horizon = {}
        for h in HORIZONS:
            target = add_trading_days(pk['recSession'], h)
            if target > year_end or not latest or target > latest:
                continue
            if closed and pk['closeDate'] <= target and pk.get('closePrice'):
                px = pk['closePrice']
            else:
                px = at_or_before(cs, target)
            s = at_or_before(spy, target)
            if px and s and pk.get('spyAtRec'):
                horizon[h] = round((px / pk['recPrice'] - 1) * 100 - (s / pk['spyAtRec'] - 1) * 100, 2)
        finals = [c for c in cs[1:] if c[2]]
        first_exit = next((c for c in finals if (lvl := exit_level_on(pk, c[0])) is not None and c[1] < lvl), None)
        done = {r.get('milestone') for r in pk.get('reflections') or []}
        sessions = sum((1 for c in cs[1:]))
        due = [m for m in (5,) + HORIZONS if m in horizon or (m == 5 and sessions >= 5) if m not in done]
        if first_exit and 'exit' not in done:
            due.append('exit')
        rows.append({'id': pid, 'ticker': pk['ticker'], 'heat': pk.get('heat'), 'setup': pk.get('setup'), 'status': pk.get('status'), 'bought': pk.get('bought'), 'recDate': pk.get('recDate'), 'amount': pk.get('amount'), 'overBudget': pk.get('overBudget') or 0, 'sessions': sessions, 'returnPct': round(ret, 2), 'vsSpyPts': round(ret - spy_ret, 2) if spy_ret is not None else None, 'vsSpyAtHorizon': horizon, 'peakPct': round((max((c[1] for c in cs)) / pk['recPrice'] - 1) * 100, 2), 'troughPct': round((min((c[1] for c in cs)) / pk['recPrice'] - 1) * 100, 2), 'exitHit': bool(first_exit), 'returnIfExitFollowedPct': round((first_exit[1] / pk['recPrice'] - 1) * 100, 2) if first_exit else None, 'reflectionDue': due[-1] if due else None, 'pastReflections': [r.get('note') for r in pk.get('reflections') or []][-2:]})
    summary = {}
    for h in HORIZONS:
        groups = {}
        for r in rows:
            v = (r.get('vsSpyAtHorizon') or {}).get(h)
            if v is not None:
                groups.setdefault(f"{r['heat']}-fire {r['setup']}", []).append(v)
        if groups:
            summary[f'{h} sessions'] = {k: {'calls': len(v), 'avgVsSpyPts': round(sum(v) / len(v), 2), 'beatRate': round(sum((x > 0 for x in v)) / len(v), 2)} for k, v in sorted(groups.items())}
    today = today_et()
    week_start = (today - dt.timedelta(days=today.weekday())).isoformat()
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    live = [pk for pk in picks.values() if pk.get('status') in ('open', 'closed')]
    this_week = [pk for pk in live if pk.get('recDate', '') >= week_start]
    ledger = {'weekOf': week_start, 'stockSpentThisWeek': round(sum((pk.get('amount') or 0 for pk in this_week)), 2), 'stockBoughtTotal': round(sum((pk.get('amount') or 0 for pk in live if pk.get('bought'))), 2), 'stockRecommendedTotal': round(sum((pk.get('amount') or 0 for pk in live)), 2), 'openMomentum': sum((1 for pk in live if pk.get('status') == 'open' and pk.get('setup') == 'Early momentum')), 'picksLast7Days': sum((1 for pk in live if pk.get('recDate', '') > week_ago)), 'openTickers': sorted({pk['ticker'] for pk in live if pk.get('status') == 'open'})}
    scored = sum((1 for r in rows if (r.get('vsSpyAtHorizon') or {}).get(20) is not None))
    return {'ledger': ledger, 'picks': rows, 'vsSpyByHorizon': summary, 'scoredAt20Sessions': scored, 'enoughToChangeRules': scored >= 30, 'note': 'Price returns only (dividends excluded). Horizons count trading days from the call; sold picks hold cash flat. Compare groups only at the same horizon.'}
BASELINE_HORIZONS = (5, 20, 60)

def with_paper(prices):
    return {k: dict(d, prices={**(d.get('paper') or {}), **(d.get('prices') or {})}) for k, d in prices.items()}

def raw_close(by_date, date, ticker):
    d = by_date.get(date) or {}
    p = (d.get('prices') or {}).get(ticker) or (d.get('paper') or {}).get(ticker)
    return p.get('close') if p else None

def vs_spy_at(series, spy, start, px0, spy0, latest, close_date=None, close_px=None):
    out = {}
    for h in BASELINE_HORIZONS:
        target = add_trading_days(start, h)
        if not latest or target > latest or not px0 or not spy0:
            continue
        if close_date and close_px and close_date <= target:
            px = close_px
        else:
            pts = [c for c in series if c[0] <= target]
            if not pts or add_trading_days(pts[-1][0], 3) < target:
                continue
            px = pts[-1][1]
        s = at_or_before(spy, target)
        if s:
            out[h] = round((px / px0 - 1) * 100 - (s / spy0 - 1) * 100, 2)
    return out

def baseline(picks_dir, prices_dir, screens_dir, top=PAPER_TOP, cooldown=20):
    import os
    picks, raw = (load_dir(picks_dir), load_dir(prices_dir))
    screens = load_dir(screens_dir) if screens_dir and os.path.isdir(screens_dir) else {}
    prices = with_paper(raw)
    by_date = {d['date']: d for d in raw.values()}
    latest = max(by_date, default=None)
    spy = closes(prices, 'SPY')
    live = [pk for pk in picks.values() if pk.get('status') in ('open', 'closed')]
    groups = {'picks': [], 'screenTop1': [], 'screenTopN': [], 'rejected': []}
    for pk in live:
        closed = pk.get('status') == 'closed' and pk.get('closeDate')
        cs = [c for c in closes(prices, pk['ticker']) if c[0] >= pk['recSession']]
        h = vs_spy_at(cs, spy, pk['recSession'], pk.get('recPrice'), pk.get('spyAtRec'), latest, pk.get('closeDate') if closed else None, pk.get('closePrice') if closed else None)
        groups['picks'].append(h)
    picked = {(pk.get('recDate'), pk['ticker']) for pk in live} | {(pk.get('recSession'), pk['ticker']) for pk in live}
    last_counted, unpriced, entries = ({}, [], 0)
    for date, rows in sorted(screen_ranks(screens, top).items()):
        for setup, rank, t, card_px in rows:
            if t in last_counted and add_trading_days(last_counted[t], cooldown) > date:
                continue
            px0, spy0 = (raw_close(by_date, date, t) or card_px, raw_close(by_date, date, 'SPY'))
            if not px0 or not spy0:
                unpriced.append(f'{t}@{date}')
                continue
            last_counted[t] = date
            entries += 1
            h = vs_spy_at(closes(prices, t), spy, date, px0, spy0, latest)
            groups['screenTopN'].append(h)
            if rank == 1:
                groups['screenTop1'].append(h)
            if (date, t) not in picked:
                groups['rejected'].append(h)
    summary = {}
    for name, hs in groups.items():
        summary[name] = {}
        for hz in BASELINE_HORIZONS:
            v = [x[hz] for x in hs if hz in x]
            if v:
                summary[name][f'{hz} sessions'] = {'n': len(v), 'avgVsSpyPts': round(sum(v) / len(v), 2), 'beatRate': round(sum((x > 0 for x in v)) / len(v), 2)}
    scored = sum((1 for x in groups['picks'] if 20 in x))
    ladder = [f'{h} sessions' for h in reversed(BASELINE_HORIZONS)]
    hz = next((k for k in ladder if k in summary['picks']), None) or next((k for k in ladder if any(k in s for s in summary.values())), None)
    if hz is None:
        line = 'Baseline check: no pick or screen candidate has reached 5 sessions yet, so there is nothing to compare.'
    else:
        fmt = lambda g: f"{summary[g][hz]['avgVsSpyPts']:+.1f} pts (n={summary[g][hz]['n']})" if hz in summary[g] else 'n/a'
        line = f"Baseline at {hz}, vs the S&P 500: real picks {fmt('picks')}, raw top screen pick {fmt('screenTop1')}, screen names the review passed over {fmt('rejected')}."
        line += ' Observations only until 30+ picks are scored at 20 sessions.' if scored < 30 else ''
    return {'line': line, 'byGroup': summary, 'groups': {'picks': 'real open and closed picks, from recPrice/spyAtRec', 'screenTop1': 'rank-1 screen candidate per setup per day', 'screenTopN': f'top {top} screen candidates per setup per day', 'rejected': 'top-N screen candidates not picked that day'}, 'paperEntries': entries, 'unpriced': unpriced[:20], 'unpricedCount': len(unpriced), 'cooldownSessions': cooldown, 'scoredAt20Sessions': scored, 'enoughToChangeRules': scored >= 30, 'note': 'Price returns only. Paper candidates are bought at the snapshot close on the screen date and held with no exit rule; a ticker counts again only after the cooldown. Compare groups only at the same horizon.'}
REQUIRED = ['date','generatedAt', 'isLastSessionOfWeek', 'marketSummary', 'lessons', 'indices', 'portfolio', 'weeklyPlan', 'recommendations', 'quotes', 'news', 'disclaimer']
INDEX_MIN = 300.0
STOCK_PLAN, STOCK_PLAN_WARN = (40000.0, 30000.0)
VANGUARD = {'VOO', 'VTI', 'VXUS', 'VEA', 'VWO', 'VTV', 'VUG', 'VOOG', 'VOOV', 'VHT', 'VGT', 'VIG', 'VYM', 'VNQ', 'BND', 'BNDX', 'VB', 'VBR', 'VO', 'VXF', 'VT', 'VDC', 'VPU', 'VDE', 'VFH', 'VIS', 'VAW', 'VCR', 'VOX', 'MGK', 'MGV'}

def whole_share_check(t, amount, shares, price, errors):
    if not isinstance(shares, int) or shares < 1:
        errors.append(f'{t}: not a Vanguard fund, so give a whole number of `shares` (at least 1)')
    elif price and amount and (abs(shares * price - amount) > max(0.03 * amount, 2)):
        errors.append(f'{t}: amount ${amount:.2f} should be shares x price ({shares} x ${price:.2f} = ${shares * price:.2f})')

def validate(brief_path, lessons_path, portfolio=None):
    with open(brief_path) as f:
        b = json.load(f)
    with open(lessons_path) as f:
        ledger = json.load(f)['ledger']
    errors, warnings = ([], [])
    for k in REQUIRED:
        if k not in b:
            errors.append(f'missing key: {k}')
    recs = b.get('recommendations', [])
    buys = [r for r in recs if r.get('action') in ('BUY', 'ADD')]
    for r in recs:
        t = r.get('ticker', '?')
        if r.get('action') not in ('BUY', 'ADD'):
            continue
        heat = r.get('heat')
        if not isinstance(heat, int) or not 1 <= heat <= 5:
            errors.append(f'{t}: BUY/ADD needs heat 1-5')
            continue
        if r.get('setup') not in ('Value', 'Early momentum'):
            errors.append(f'{t}: BUY/ADD setup must be Value or Early momentum (funds go in weeklyPlan)')
        if r.get('setup') == 'Early momentum' and heat > 4:
            errors.append(f'{t}: momentum-only setups cap at 4 fires')
        if not r.get('exitPlan'):
            errors.append(f'{t}: missing exitPlan')
        if r.get('setup') == 'Early momentum' and r.get('exitLevel') is None:
            errors.append(f'{t}: momentum buys need a numeric exitLevel')
        elif r.get('exitLevel') is None:
            warnings.append(f'{t}: no numeric exitLevel; say why in exitPlan')
        amt = r.get('amount') or 0
        whole_share_check(t, amt, r.get('shares'), r.get('price'), errors)
        cap = BASE_AMOUNT[heat] * 1.25
        if not amt:
            errors.append(f'{t}: missing amount')
        elif amt > cap and r.get('shares') != 1:
            warnings.append(f'{t}: ${amt:.0f} is above the {heat}-fire size (${cap:.0f}); check the sizing (1 share over the size is fine)')
        if portfolio and amt > 0.03 * portfolio:
            errors.append(f'{t}: ${amt:.0f} is over 3% of the portfolio (${0.03 * portfolio:.0f})')
        if r.get('overBudget'):
            warnings.append(f'{t}: overBudget is no longer used; set it to 0')
        if not (r.get('debate') or {}).get('bear'):
            warnings.append(f'{t}: no bear case recorded')
        if t in ledger.get('openTickers', []):
            warnings.append(f'{t}: already has an open pick; explain why this is a new, stronger entry')
    today_stock = sum((r.get('amount') or 0 for r in buys))
    bought_total = ledger.get('stockBoughtTotal', 0)
    if bought_total >= STOCK_PLAN_WARN:
        warnings.append(f'single stocks bought so far: ${bought_total:,.0f}, past ${STOCK_PLAN_WARN:,.0f} of the ~${STOCK_PLAN:,.0f} plan; warn the investor in marketSummary')
    elif bought_total + today_stock > STOCK_PLAN_WARN:
        warnings.append(f"today's buys would take single-stock spend to ${bought_total + today_stock:,.0f}, past ${STOCK_PLAN_WARN:,.0f} of the ~${STOCK_PLAN:,.0f} plan; warn the investor in marketSummary")
    wp = b.get('weeklyPlan') or {}
    index_total = sum((i.get('amount') or 0 for i in wp.get('items', []) if i.get('kind') == 'index'))
    for i in wp.get('items', []):
        if i.get('kind') == 'index' and i.get('ticker') not in VANGUARD:
            whole_share_check(i.get('ticker', '?'), i.get('amount') or 0, i.get('shares'), i.get('price'), errors)
    if b.get('weeklyRecap') is None and b.get('isLastSessionOfWeek'):
        errors.append('last session of the week: add weeklyRecap')
    if wp and index_total + 0.01 < INDEX_MIN:
        errors.append(f'weeklyPlan puts ${index_total:.0f} in index funds; the minimum is ${INDEX_MIN:.0f}')
    plan_stocks = {i.get('ticker') for i in wp.get('items', []) if i.get('kind') == 'stock'}
    for r in buys:
        if wp and r.get('ticker') not in plan_stocks:
            warnings.append(f"{r.get('ticker')}: add today's buy to weeklyPlan.items (kind stock)")
    if wp.get('overBudget'):
        warnings.append('weeklyPlan.overBudget is no longer used; set it to 0')
    new_mom = sum((1 for r in buys if r.get('setup') == 'Early momentum' and r.get('ticker') not in ledger.get('openTickers', [])))
    if ledger['openMomentum'] + new_mom > 2:
        errors.append(f"would make {ledger['openMomentum'] + new_mom} open momentum picks (max 2)")
    if ledger['picksLast7Days'] + len(buys) > 2:
        errors.append(f"would make {ledger['picksLast7Days'] + len(buys)} new picks in 7 days (max 2)")
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'stockToday': today_stock, 'stockBoughtTotal': bought_total, 'stockPlanLeft': round(STOCK_PLAN - bought_total, 2), 'indexTotal': index_total}
if __name__ == '__main__':
    try:
        arg = lambda name, default=None: float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
        if len(sys.argv) > 1 and sys.argv[1] == 'session':
            now = dt.datetime.now(ZoneInfo('America/New_York'))
            date, prev, intraday, holiday = session(now)
            print(json.dumps({'date': date, 'prevSession': prev, 'intraday': intraday, 'holiday': holiday, 'earlyClose': now.date().isoformat() in EARLY_CLOSE, 'lastSessionOfWeek': last_session_of_week(dt.date.fromisoformat(date))}))
            sys.exit(0)
        if len(sys.argv) > 1 and sys.argv[1] == 'validate':
            print(json.dumps(validate(sys.argv[2], sys.argv[3], arg('--portfolio')), indent=1))
            sys.exit(0)
        if len(sys.argv) > 1 and sys.argv[1] == 'lessons':
            print(json.dumps(lessons(sys.argv[2], sys.argv[3]), indent=1))
            sys.exit(0)
        top = int(arg('--top', PAPER_TOP))
        if len(sys.argv) > 1 and sys.argv[1] == 'baseline':
            print(json.dumps(baseline(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith('--') else None, top, int(arg('--cooldown', 20))), indent=1))
            sys.exit(0)
        screens_dir = sys.argv[sys.argv.index('--screens') + 1] if '--screens' in sys.argv else None
        flags = {'--screens', '--top'}
        tickers = [a for i, a in enumerate(sys.argv[1:], 1) if a not in flags and sys.argv[i - 1] not in flags]
        print(json.dumps(main(tickers, screens_dir, top), indent=1))
    except Exception as e:
        print(json.dumps({'error': str(e)}))
