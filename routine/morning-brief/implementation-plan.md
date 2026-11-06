# Morning Brief upgrades: implementation plan

Files (all in this scratchpad): `routine-prompt-changes-v2.md` (exact prompt edits, supersedes v1),
`tv_track_v2.py` (drop-in replacement for `/tmp/tv_track.py`), `tools/make_fake.py` (test-data generator), `testbrief/` (test copy of `/tmp/brief`).

## 1. What changes where
| # | Change | Prompt (v2 item) | Script |
|---|--------|------------------|--------|
| 1 | Up to 25 searches; 2 macro searches first; a cited cause in marketSummary when the S&P 500 or Nasdaq moves >1.5% | 5, 7 | none |
| 2 | Up to 5 finalists; read each finalist's latest earnings release/guidance, with report date; no confirmed release in 100 days caps the rating at Overweight | 5, 6 | none |
| 3a | Price the screen candidates daily | 1, 2, 4, 8 | `tv_track.py <tickers> --screens DIR [--top 10]` |
| 3b | Report picks vs raw screen vs rejected, against SPY at 5/20/60 sessions | 3, 9 | `tv_track.py baseline PICKS PRICES SCREENS [--top 10] [--cooldown 20]` |

Why 3a is needed: `screens/<date>` stores candidates but `prices/<date>` only held open picks + SPY, so a paper pick
had an entry price (the card) but never an exit price. Also, `/tmp/brief/screens` was never downloaded, and today's
screen only reaches the DB in step 3, so the prompt now also writes it to `/tmp/brief/screens/<today>.json` locally.

## 2. Data-shape changes
- `prices/<date>` gains an optional `paper: {TICKER: {close, prevClose}}`. It holds the top 10 per setup from every
  screen dated within the last 60 sessions (+1), minus tickers already in `prices`. `prices` is unchanged, so `lessons`,
  the pick charts and old docs are unaffected. Old docs without `paper` still load.
- `screens/<date>`: unchanged (`{date, value, momentum}`), but ranking order now matters (rank 1 = first card).
- `briefs/<date>.lessons`: one more string, the baseline `line`.
- No change to `picks/*`, `holdings`, `history/backfill`.

## 3. tv_track_v2.py: what was added (about 110 lines; nothing removed)
- `screen_ranks`, `paper_tickers`: pick the top N per setup still inside the 60-session window (capped at 300 names).
- `main(tickers, screens_dir, top)`: one scanner call for picks + paper names; paper names go under `paper`.
  Without `--screens` the output is byte-for-byte the old shape.
- `baseline(...)`: groups `picks` (recPrice/spyAtRec, closed picks held as cash after closeDate, the same rule as `lessons`),
  `screenTop1` (rank-1 per setup per day), `screenTopN` (top N), `rejected` (top N not picked on that date).
  Paper entries are bought at that day's raw snapshot close (the same price source as `recPrice`), against the raw SPY close.
  They are held with no exit rule. A ticker re-enters only after a 20-session cooldown, so names that stay on the screen for weeks aren't counted many times.
  A horizon is skipped if the last price is more than 3 sessions stale. `enoughToChangeRules` uses the same 30-at-20-sessions rule.

## 4. Tests run (all with `python3 -I`)
- `py_compile` OK. `lessons` output identical to the old script on `/tmp/brief` and on the test copy (which has `paper` rows);
  `validate /tmp/brief.json /tmp/lessons.json --portfolio 100000` identical; `session` identical.
- `paper_tickers` on the test screens: 22 names for 2026-11-05; [] for 2027-03-01 (window passed); [] with no dir.
- Live snapshot `BR CI DVN TEL --screens <dir with today's screen>` returned `prices` for the 4 picks + SPY and
  `paper: {YUMC: {close 49.85, prevClose 49.68}, PLMR: {close 154.31, prevClose 144.04}}`; without `--screens` the keys are unchanged.
- `baseline` on the real sample (no screens yet) gives the line
  "Baseline at 5 sessions, vs the S&P 500: real picks +2.9 pts (n=4), raw top screen pick n/a, screen names the review passed over n/a. ..."
- `baseline` on `testbrief/` (22 fake screens, ZVA*/ZMO* fake tickers, synthetic prices; `/tmp/brief` untouched):
```
$ python3 -I tv_track_v2.py baseline testbrief/picks testbrief/prices testbrief/screens
"line": "Baseline at 5 sessions, vs the S&P 500: real picks +2.9 pts (n=4), raw top screen pick +2.9 pts (n=6),
         screen names the review passed over +1.4 pts (n=16). Observations only until 30+ picks are scored at 20 sessions."
"byGroup": picks      {5: n4  +2.90 beat .75}
           screenTop1 {5: n6  +2.88 beat .67, 20: n2  +5.25 beat .50}
           screenTopN {5: n20 +1.71 beat .75, 20: n12 +7.49 beat .75}
           rejected   {5: n16 +1.41 beat .75, 20: n12 +7.49 beat .75}
"paperEntries": 32, "unpricedCount": 0, "scoredAt20Sessions": 0, "enoughToChangeRules": false
```
  (Fake numbers only show that the plumbing works. The line uses the longest horizon at which real picks have data.)

## 5. Risks and limits
- **Runtime/tokens:** 25 searches plus 5 finalists with earnings reads is roughly 2-2.5x the research tokens and adds
  ~5-10 min of runtime. Keep the "send searches in as few turns as possible" rule. Search results are the biggest token cost,
  so ask for summaries, not full pages. The prompt grows ~3 KB of text, plus ~7 KB for the larger script (48 KB to ~58 KB).
- **DB doc size:** the tool documents a 1 MiB batch cap but no per-doc cap, so assume a small one (keep docs under ~64 KB).
  `paper` costs ~45 bytes per name. Realistic load is 20-80 names (~1-4 KB). The hard cap of 300 names is ~14 KB. Test prices doc: 0.95 KB to 1.8 KB.
  `screens/<date>` with 10+10 full cards is ~25 KB, unchanged.
- **Listing:** `list prices`/`screens` default to 100 docs per page; after ~5 months, page with `query.cursor` or
  `limit: 1000`. The prompt now says "all pages".
- **Dashboard:** check that the page ignores the unknown `paper` key (it should, since charts read `prices[ticker]`).
- **Bias:** the screen runs with `--exclude` (open picks + holdings of 3% or more) and `--max-price 600`, so "raw screen" means
  raw *after* those filters. Picks use real exits/closes; paper names use buy-and-hold. Dividends are excluded everywhere.
- **Small n:** months pass before 20/60-session cells are meaningful. The rating rules stay frozen until 30+ picks are scored at 20 sessions.
- **Cause rule:** a forced "cause" can tempt the model to over-claim. The prompt requires a cited source or the words "not yet clear".

## 6. Rollout order
1. Replace the `/tmp/tv_track.py` block in the Scripts section with `tv_track_v2.py` (v2 item 10). It is backward-compatible and safe alone.
2. Data plumbing: items 1, 2, 4, 8 (download screens, local copy of today's screen, `--screens` snapshot). Run once and
   check that `prices/<today>` has `paper` and the dashboard still renders.
3. Baseline reporting: items 3, 9. Day 1 shows "n/a" for screen groups. The first screen numbers appear after 5 sessions.
4. Research upgrades: items 5, 6, 7 (searches, finalists, earnings, cited cause). Watch the first 2-3 runs for duration and token use.
5. Optional timing line (item 4b) only if the schedule moves to ~10:30 ET.
Rollback: restore the old script block. Old and new docs stay readable because `paper` is additive.

## 7. Investor decisions
- N priced per setup (`--top`, default 10, decided by the investor; doubles the paper rows vs 5).
- Cooldown before a re-listed name counts again (default 20 sessions).
- Whether "no earnings release in 100 days caps at Overweight" is the right strictness.
