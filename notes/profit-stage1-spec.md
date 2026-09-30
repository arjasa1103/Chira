# Stage 1a specification: does the liquidity signal survive bet-time information?

**Pre-commitment.** This file is committed before any number in it is computed from NBA
2025-26, exploratory looks included. Its value is its commit timestamp, which anyone can check
against the later verdict. It fixes a method, not fitted parameters.

Lines marked *(proposed)* were open choices when this was written. They are fixed from this
commit on.

Verdict due **2026-10-06**. No verdict by then counts as a kill for the 2026-27 opener.
The verdict is written up whatever it says.

---

## 1. The question

Chira's headline 2 found NBA thin markets underconfident (Cox slope +1.398) and liquid markets
overconfident (+0.586), difference +0.812, 95% CI [+0.618, +1.033]. That split used **terminal**
volume, which does not exist at bet time. Stage 1a asks whether the effect survives when the
split uses only information available **before** the bet, and whether betting it clears costs.

**Honest caveat, stated up front:** headline 2 already looked at both seasons, so this test is
not blind. Only live 2026-27 paper trading is.

## 2. Data

- Chira's immutable census snapshot, read through `chira.analysis` (home side only, one row per
  game, canonical order, league-sourced label).
- **Fit season:** NBA 2024-25. **Evaluation season:** NBA 2025-26. NHL is reported, never
  gating.
- Market-only: prices, the change count, terminal volume, outcomes. **No Chira model output**
  (holdout firewall).
- Games with `volume_source = 'absent'` are excluded from the rho test (Amendment 4). They stay
  in the strategy evaluation, where the change count, not volume, assigns the stratum.
- The away side is the complement of the home side: `p_fair(away) = 1 − p_fair(home)`.
  *(proposed)*

## 3. The bet-time liquidity measure

- **Measure:** the count of price changes in the raw 1-minute series from market open to
  **T-6h**, T = the league's start time (Amendment 1).
- **Cut:** the **NBA 2024-25 median** of that count, learned once, applied unchanged to
  2025-26 and to live 2026-27. `low` = count ≤ cut. No current-season re-cut. If counts trend
  up across seasons, more games land `high` later; that is accepted and reported.
- **Proxy fitness gate:** Spearman rho between the count and terminal volume, **computed on NBA
  2024-25**, 2025-26 reported beside it. **rho < 0.5 → the proxy is unfit and 1a fails.** No
  second proxy is tried on this data.
- **Also reported:** the misclassification rate implied by the observed rho (share of games
  whose count-stratum differs from their terminal-volume stratum), and listing-duration
  stability (hours from market open to T-6h) across both seasons.

## 4. Prices, costs, fee

- **Executable price at T-1h:** the last raw-series point at or before T-1h (`p_t1h`). The
  series is a normalized complementary price, not a quote, so it is treated as a **mid**.
- **Cost grid:** half-spread ∈ {1c, 2c, 3c} × fee ∈ {0, published}.
  **Pass/kill cell: 2c half-spread, published fee.**
- **Published fee** (Polymarket sports, read 2026-09-29): `fee = shares × 0.05 × p × (1 − p)`,
  applied as a per-share price addition `0.05·p·(1−p)`.
- **Fee regime of the training seasons:** did any taker fee apply to sports markets in
  2024-25 and 2025-26? The current fee can change who trades thin markets, so this is stated,
  not assumed.
  - **2024-25: no.** Polymarket charged no trading fees on sports markets.
  - **2025-26: no for most of the season, yes from 2026-03-30.** Taker fees first reached
    sports on 2026-02-18, and only for NCAAB and Serie A. "Fee Structure V2" extended them to
    all sports markets, NBA and NHL included, on 2026-03-30 at a sports rate of `0.03`
    (peak 0.75c per share at p = 0.50). That covers roughly the last two weeks of the NBA
    regular season and any playoff games in the census. The rate rose to `0.05` on
    2026-07-10, after the season.
  - Source: Polymarket documentation changelog (docs.polymarket.com/changelog: entries of
    2026-02-11, 2026-03-30, 2026-07-10) and the fees page, read 2026-09-30.
  - *(proposed)* Report the 2025-26 evaluation split at 2026-03-30 (no-fee vs fee regime) as a
    sensitivity. It does not gate.

## 5. Recalibration map and bet rule

- **Map:** Cox intercept and slope per stratum, `logit(p_fair) = a_s + b_s·logit(p)`, fit on
  NBA 2024-25 only with `chira.calibration.cox_slope_intercept`, applied to 2025-26 unchanged.
- **Bet rule:** bet the side where `p_fair > p + half_spread + fee(p)`. At most one side per
  game. Flat 1-unit stake.
- **Settlement:** with `p_paid = p + half_spread + fee(p)`, a winning bet returns
  `1/p_paid − 1` units and a losing bet loses 1 unit.

## 6. Evaluation

- **ROI** on NBA 2025-26 at every grid cell, with a **date-clustered bootstrap 90% interval**
  (resample ET dates, not games; bets on the same night share news).
- **Bet-time slope difference** (low − high) on 2025-26 under the fixed 2024-25 cut, with a
  date-clustered bootstrap **95%** interval, via `chira.strata.clustered_slope_difference`.
  Also reported on 2024-25; only 2025-26 gates.
- Bootstrap: **2,000 reps, seed `0`**, stated in the output. Seed 0 and 2,000 reps match headline 2's date-clustered run
  (`chira.strata` default seed; `scripts/run_headline2.py`), so the two are comparable. *(proposed)* Report any p-value
  as a bound when it hits the resolution floor, as headline 2 does.
- Every published figure is rounded once, from the output JSON, never from an intermediate.

## 7. Kill criteria

**Any one kills Signal L:**

1. rho < 0.5 on NBA 2024-25.
2. The 2025-26 bet-time slope-difference 95% CI includes 0.
3. The 2025-26 slope-difference point estimate has the **opposite sign** to 2024-25.
4. The 2025-26 ROI 90% interval **upper bound < 0** at the pass/kill cell.

A positive ROI point estimate with an interval straddling zero **passes as a screen only**. The
real test is live paper trading.

## 8. What the report must end with

- **Sizing:** capacity × edge × fire rate = expected dollars per season, where capacity comes
  from depth (NBA 2024-25 median terminal volume $296k; the 20%-of-depth-within-2c rule caps
  the stake).
- **Fire rate** per game, and whether it reaches **200 NBA bets by mid-April**. If not, the
  signal is declared untestable this season.
- **A Stage 2 vendor spend ceiling** set against the sizing, before any purchase.
- The verdict: pass, screen-pass, or kill, with the criterion that decided it.

## 9. If it passes

Refit the map **once** on NBA 2024-25 + 2025-26 with the same fixed cut and freeze it. Its
fitted parameters stay private; their sha256, over a canonical serialization (sorted keys,
fixed float formatting), is committed to this repository **before 2026-10-20**, so the map can
later be checked as frozen before any 2026-27 game. Never refit during the season. The only
exit is the pre-committed drift stop: after 150 live NBA games, if the low − high Cox slope
difference on 2026-27 falls below a quarter of the 2025-26 value from section 6, Signal L stops
for the season.
