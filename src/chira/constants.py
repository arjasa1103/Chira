"""Facts about the Polymarket API, all verified by live probe.

Every constant here was established empirically during planning. The comments
record the evidence, because several of these look wrong until you know why.
"""

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
# Probed 2026-09-12; see notes/week2-nhl-schedule.md. Lives here with its two
# peers so "which third parties does this study depend on" is one file, not three.
NHL_API = "https://api-web.nhle.com/v1"

# Slug dates are USUALLY the US-Eastern local game date, but NOT ALWAYS.
#
# CORRECTED in week 1. An earlier probe of 11 games concluded "always ET"; that
# sample happened to sit entirely on one side of a convention change. Probing
# 90 stratified games across both usable seasons found:
#
#   2025-26 Oct:        2 ET, 1 UTC
#   2025-26 Nov:        6 ET, 3 UTC
#   2025-26 Dec-Apr:   33 ET, 0 UTC
#   2024-25 (all):     45 ET, 0 UTC
#
# So during roughly the first six weeks of 2025-26, some games were slugged with
# the UTC date instead. It is not sport-based and not tipoff-hour-based:
# nba-phx-uta-2025-10-28 and nhl-wsh-chi-2026-01-09 share an 01:00Z tipoff and
# use different conventions. Looks like an upstream slug-generation bug that was
# fixed around late November 2025.
#
# CONSEQUENCE: slug construction MUST try both the ET date and ET+1. Trying only
# ET silently loses ~12% of early-2025-26 games and records them as "no market",
# which corrupts the coverage chart that gates the whole project.
# NOTE: no SLUG_TZ constant. Deriving the ET date from gameStartTime is
# explicitly forbidden (see schedule.py rule 1) because the schedule already
# carries it; a tz constant here would be a live foothold for that mistake.
SLUG_DATE_CONVENTIONS = ("et", "et_plus_1")

# `fidelity` is documented as "Accuracy of the data expressed in minutes.
# Default is 1 minute." (docs.polymarket.com, confirmed week 1).
FIDELITY_MINUTES = 1

# Usable backtest window. 2023-24 is EXCLUDED: probed Dec-2023 NBA markets
# carry $6/$0/$0/$0 volume and Mar-2024 has zero sports slugs, so those prices
# are not calibrated probabilities. Do not "fix" the missing season.
USABLE_SEASONS = ("2024-25", "2025-26")

# Per-game liquidity quadrupled between the two usable seasons
# (~$500k in 2024-25 vs ~$1.9M in 2025-26). They are different market regimes;
# report them separately as well as pooled.
SEASON_MEDIAN_VOLUME_HINT = {"2024-25": 5.0e5, "2025-26": 1.9e6}

# Gamma /markets silently caps `limit` at 100 and returns nothing past
# offset ~2100. You CANNOT enumerate a date window by paginating; drive
# enumeration from the league schedule instead.
GAMMA_LIMIT_CAP = 100
GAMMA_OFFSET_CEILING = 2100

# Slug lookup requires /events?slug=; /markets?slug= returns [].
# prices-history requires startTs + fidelity; interval=max with fine fidelity
# silently returns HTTP 200 with an empty history[] for markets that ended long
# ago, and startTs+endTs together returns HTTP 400 "interval is too long".
# Pre-2022 (pre-CLOB) markets have no price history at any fidelity.

# The two outcome tokens are exact complements: last pre-tipoff values summed to
# 1.0000 on all three probed games. Enforce it, do not trust it.
COMPLEMENTARITY_TOL = 1e-6

# A flat run of this many identical consecutive minute values immediately
# pre-tipoff flags a game as stale (carry-forward, not live quoting).
# Measured: 53/128 sampled games (41%) trip this.
STALE_FLAT_RUN = 10

# Resolution ties. outcomePrices ["0.5","0.5"] means postponed/split. It must be
# tested BEFORE the complementarity branch: 0.5+0.5 sums to exactly 1.0, so a
# complementarity-first ordering made the tie branch unreachable and silently
# labelled every postponed game an away win.
TIE_TOL = 1e-9

# Price-window construction. Fallback lookback when a market carries no
# startDate (markets open ~7 days pre-game), and a pad so the first point of
# the series is not clipped by rounding.
DEFAULT_LOOKBACK_DAYS = 7
HISTORY_PAD_SECONDS = 3600

# Adopted integrity gate, derived from simulate_null against a measured price
# pool (see PREREGISTRATION.md section 4). Every bound is rounded OUTWARD from
# the simulated null p99 / 95% CI: rounding inward re-creates the false-fire
# defect the simulation existed to remove.
#   null p99 ECE at n=5,084 = 0.0260  -> gate 0.03
#   null p99 max-bin-dev    = 0.0713  -> gate 0.08
#   null 95% CI slope       = [0.9305, 1.0703] -> gate [0.93, 1.08]
#   null 95% CI intercept   = [-0.0612, 0.0640] -> gate [-0.07, 0.07]
GATE_ECE_MAX = 0.03
GATE_MAX_BIN_DEV = 0.08
GATE_SLOPE_BAND = (0.93, 1.08)
GATE_INTERCEPT_BAND = (-0.07, 0.07)

# Miss reason enum. Every scheduled game that is not `priced` carries exactly
# one of these, and the store rejects anything else: an unconstrained reason
# string is how "no market exists" and "we never tried the right slug" end up
# as the same row, which is the one distinction the coverage chart depends on.
MISS_REASONS = (
    # every candidate slug missed; re-probed once with the cache bypassed UNLESS
    # the run passed --no-reprobe, which nothing on the row records
    "no_market",
    "no_pre_tipoff_points",            # market exists, price series empty before tipoff
    "unparseable_market",              # clobTokenIds / outcomes malformed
    "missing_gameStartTime",
    "unparseable_gameStartTime",
    "postponed_or_split_resolution",   # outcomePrices ["0.5","0.5"]
    "outcome_prices_not_complementary",
    "malformed_outcome_prices",
    "complementarity_failed",          # last pre-tipoff prices do not sum to 1
    "label_mismatch_at_slug",          # a slug returned events, none matched the teams
    "implausible_game_start_time",     # market tipoff disagrees with the schedule
    "no_moneyline_market",             # teams matched, but only spread / half-game markets
    "unresolved_market",               # market exists but carries no outcomePrices
    "label_disagreement",              # E1: market winner != league winner
)

# Tipoff plausibility. `gameStartTime` comes from the same third party being
# benchmarked and is the pre-tipoff cutoff, so when it is late the "closing"
# price is a settled price. Live example: nba-dal-uta-2024-11-14 carries a
# 00:57 ET tipoff (about 4 hours late) and stored p_home_close = 0.9995 on a
# 115-113 game, i.e. a perfect predictor manufactured by a bad timestamp.
#
# Measured over the 960 priced games in the week-2 slices: 959 have an ET tipoff
# date equal to the schedule's ET date, and the hour histogram runs 12..23. The
# band below is one hour wider on the early side; it rejects exactly the two
# known-bad rows and nothing else.
TIPOFF_ET_HOUR_BAND = (11, 23)

# Market selection. Gamma events carry many markets whose outcome labels are the
# two team names -- the moneyline, but also "Spread: Capitals (-1.5)" and, for NBA
# 2025-26, a first-half moneyline. Taking the first label match priced 5 NHL
# 2025-26 SPREAD markets as moneylines (all April 2026); label agreement caught two
# more only because the favourite won by exactly one goal. 1,212 NBA 2025-26 and 580
# NHL 2025-26 events were exposed and got the moneyline only because it happened to
# be listed first. Every cached event carries `sportsMarketType`, so select on it.
#
# The field is not perfect: 40 NBA 2024-25 single-market events ("Thunder vs.
# Nuggets", team-name outcomes, label agreement passing) are typed `totals`. A real
# totals market has Over/Under outcomes and cannot label-match two teams, so a SOLE
# label-matching market is accepted unless its type names a non-full-game market.
MONEYLINE_MARKET_TYPE = "moneyline"
NON_FULL_GAME_MARKET_TYPES = frozenset({
    "spreads", "first_half_moneyline", "first_half_spreads", "first_half_totals",
})
NON_FULL_GAME_MARKERS = ("spread", "half", "period", "quarter", "inning")
