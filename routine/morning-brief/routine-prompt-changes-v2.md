# Morning Brief routine: prompt changes v2 (paste into the routine settings)

Supersedes `routine-prompt-changes.md`. Each item gives the exact current text ("Replace") and its replacement ("With"); paste the text between the outer quotes. Every "Replace" string was checked to occur exactly once in the routine prompt as it ran on 2026-11-05. Apply them in the order of `implementation-plan.md`.

## 1. Dashboard database: `screens` line
Replace:
"- `screens/<YYYY-MM-DD>`: today's raw screen candidates (paper picks), so later we can test whether the full review beats the raw screen."
With:
"- `screens/<YYYY-MM-DD>`: today's raw screen candidates (paper picks), so later we can test whether the full review beats the raw screen. The top 10 per setup are priced every day for 60 sessions in the `paper` field of `prices/<date>`, and the `baseline` command scores them."

## 2. Step 1: download screens too
Replace:
"   - `list` `picks` and `prices` with `out_dir: /tmp/brief`; files land in `/tmp/brief/picks/` and `/tmp/brief/prices/`."
With:
"   - `list` `picks`, `prices` and `screens` with `out_dir: /tmp/brief` (all pages; use `query.limit` 1000); files land in `/tmp/brief/picks/`, `/tmp/brief/prices/` and `/tmp/brief/screens/`."

## 3. Step 2: baseline check (add after the **Reflections** bullet)
Add:
"   - **Baseline check:** run `python3 /tmp/tv_track.py baseline /tmp/brief/picks /tmp/brief/prices /tmp/brief/screens > /tmp/baseline.json`. It compares, against SPY (the index-fund baseline) at 5, 20 and 60 sessions: real picks, the raw rank-1 screen candidate per setup, and the top screen candidates the review did not pick. Copy its `line` into `lessons`, word for word, as the last entry. Do not change how you rate deals because of it until `enoughToChangeRules` is true (30+ picks scored at 20 sessions). If it prints `error`, leave the line out and say so in your final summary."

And in the **Lessons** bullet, replace "Put 1-2 observations in `lessons`." with "Put 1-2 observations in `lessons`, plus the baseline line."

## 4. Step 3: keep a local copy of today's screen; timing line
Replace:
"Save the whole output (minus `notes`) to `screens/<today>` as `{date, value, momentum}`."
With:
"Save the whole output (minus `notes`) to `screens/<today>` as `{date, value, momentum}`, and write the same JSON to `/tmp/brief/screens/<today>.json` so step 7 prices today's candidates. Keep the screen's ranking order; do not reorder or drop candidates."

Optional (only if the schedule moves to about 10:30 am ET). Replace:
"   - The run is about 2.5 hours after the open, so prices are intraday (delayed about 15 minutes)."
With:
"   - The run is about 1 hour after the open, so prices are intraday (delayed about 15 minutes) and relative volume is still building; treat relVolume below 0.9 as unreliable before 11:30 am ET and do not reject a momentum candidate on that alone."

## 5. Step 4: up to 5 finalists, 25 searches, macro first, earnings releases
Replace:
"4. **Analyst team (repo roles).** Pick at most 3 finalists from the screens."
With:
"4. **Analyst team (repo roles).** Pick at most 5 finalists from the screens."

Replace the whole **News and sentiment** bullet:
"   - **News and sentiment**: about 10 web searches in total for the whole run. That's one macro search ("stock market today <date>"), one per finalist (news, earnings date confirmation, analyst changes), and one per holding with notable news. Send them in one turn."
With:
"   - **News and sentiment**: up to 25 web searches in total for the whole run, sent in as few turns as possible:
     - **First, two macro searches**: "stock market today <Month D, YYYY>" and "why stocks <rose|fell> today <Month D, YYYY>" (pick the word from the S&P 500's direction in tv_quotes). If the S&P 500 or the Nasdaq moved more than 1.5% either way, you must find the cause: if both searches miss it, run up to two more (e.g. "<index> selloff <Month D> reason", "Nasdaq <Month D, YYYY> chip stocks").
     - **Per finalist (up to 5), two searches**: (a) latest news, earnings date confirmation and analyst changes; (b) the most recent earnings release or guidance (company press release, 8-K or earnings call summary). Note the report date and the headline numbers (revenue, EPS, guidance raised/kept/cut).
     - One per holding that moved more than 5% today or reports earnings within 5 trading days.
     - Check every result's date and ignore results from other years or other days."

## 6. Step 5: earnings check (add as the first bullet)
Add:
"   - **Earnings check:** before the bear case, state what the latest earnings release and guidance said, with the report date, from the step 4 search. Put it in `debate.bear` or `debate.bull`. A finalist with no confirmed earnings release from the last 100 days cannot be rated above Overweight."

## 7. Step 6: cited cause for big index moves
Replace:
"   - Start `marketSummary` with the portfolio's biggest allocation issue if there is one (e.g. "55% tech; new money should go elsewhere"), then whether today has a real deal."
With:
"   - Start `marketSummary` with the portfolio's biggest allocation issue if there is one (e.g. "55% tech; new money should go elsewhere"), then whether today has a real deal.
   - If the S&P 500 or the Nasdaq is up or down more than 1.5%, `marketSummary` must say why in one clause, and `news` must include the cited source for that cause (with its URL). Only after four searches have failed may you write "the cause is not yet clear", and then say so in the disclaimer too."

## 8. Step 7: price snapshot includes screen candidates
Replace:
"7. **Price snapshot.** Run `python3 /tmp/tv_track.py <every open pick ticker plus today's BUY/ADD tickers>`. SPY is added automatically. Write its output, without `missing`, to `prices/<its date>`:"
With:
"7. **Price snapshot.** Run `python3 /tmp/tv_track.py <every open pick ticker plus today's BUY/ADD tickers> --screens /tmp/brief/screens`. SPY is added automatically, and so are the top 10 candidates per setup from every screen of the last 60 sessions (under `paper`, close and prevClose only). Write its output, without `missing`, to `prices/<its date>`, keeping `paper`:"
(The rest of step 7 stays as it is.)

## 9. Step 9: email scorecard
Replace:
"a one-line pick-tracker scorecard (calls tracked, average vs S&P);"
With:
"a one-line pick-tracker scorecard (calls tracked, average vs S&P) followed by the baseline line from step 2;"

## 10. Scripts section
Replace the whole `### /tmp/tv_track.py` code block with the contents of `tv_track_v2.py` (same file name, `/tmp/tv_track.py`). `session`, `lessons`, `validate` and the plain snapshot call behave exactly as before.

## Carried over from the first draft, unchanged
- Holdings added outside the picks log (optional), step 1: "Single stocks the investor bought that were not brief picks appear in `holdings` only. In marketSummary, count them in 'single stocks bought so far' by adding the cost basis of any single-stock holding whose avgCost purchase was not a pick (ask the investor if unsure)."
- Second trading-bot repo: still needs the repo name and which parts to combine.
