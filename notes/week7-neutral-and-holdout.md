# The NBA neutral-site list, and the seal on the holdout

Two items closed before week 8, both of them preconditions for the model rather than
parts of it: Amendment 5b needs a neutral-site list the NBA does not publish correctly,
and Amendment 5e needs the holdout to be openable exactly once.

## The NBA neutral-site list

**The gap.** `nhl.nhl_games` reads `neutralSite` and the census stores it, flagging 10
games across the two seasons. `schedule.nba_games` reads nba_api's `LeagueGameFinder`,
whose stat rows carry **no venue field at all**, so every one of the 2,460 NBA rows says
`neutral_site = FALSE` *by construction, not by measurement*. The feature store was
therefore computing travel to and from the nominal home team's city for games played in
Paris.

**The source.** `stats.nba.com/stats/scheduleleaguev2` does carry `arenaName`,
`arenaCity`, `arenaState` and `isNeutral`. Three requests cover 2023-24, 2024-25 and
2025-26 — the two census seasons plus the Elo burn-in season Amendment 5b requires.

**The league's own flag is wrong, and trusting it would have been silent.** All four
genuinely neutral 2023-24 games carry `isNeutral: false`, while the identical fixtures
in the two later seasons carry `true`:

| season | Mexico City | Paris / London / Berlin | NBA Cup semifinals, Las Vegas | `isNeutral` |
|---|---|---|---|---|
| 2023-24 | 1 | 1 | 2 | **all false** |
| 2024-25 | 1 | 2 | 2 | all true |
| 2025-26 | 1 | 2 | 2 | all true |

So the derivation does not read the flag. It compares `arenaCity` against the home
team's own city, which is measurable and cannot be silently wrong in the same way.
`scripts/fetch_neutral_sites.py` re-runs exactly that comparison and diffs it against
the vendored table, exiting non-zero on any disagreement. It reports the flag separately
so the upstream defect stays visible.

**Two findings I would not have guessed, and one I would have got wrong.**

- **The Emirates NBA Cup semifinals are regular-season games at a neutral site.** Two a
  year, in Las Vegas, with `gameId` starting `002`. They are in the census, priced, and
  were being scored as ordinary home games. The final is not a regular-season game and
  does not appear.
- **A home-and-away pair within four days is not a usable signature** for the
  international series. I checked: 63 NBA pairs match that pattern and almost all are
  ordinary scheduling. The arena city is the only reliable discriminator.
- **Relocated home games are not neutral sites, and the distinction matters.** The Spurs
  play two games a season at the Moody Center in Austin. That is 120 km from home in
  front of their own crowd, so calling it neutral would zero a real home advantage to
  fix a travel error four times smaller than the median trip. They are vendored
  separately as `NBA_RELOCATED_HOME` — recorded, deliberately inert. Same class, no row
  needed: the Clippers played 2023-24 at Crypto.com Arena and moved to the Intuit Dome
  for 2024-25, 9 km away, and the burn-in season does not use travel at all.

**Effect on the feature store.** NBA game-sides with no known venue went from **0 to 18
per season** — the five neutral games themselves plus the next game for each team, since
you cannot measure the leg out of a venue you do not know. Median NBA travel moved from
1,012 to 1,003 km (2024-25) and 985 to 976 km (2025-26), the wrong long-hauls coming
out. PREREGISTRATION Amendment 5d already fixes what the model does with a NULL: fill
with the sport's 2024-25 median and report the count.

The override is an **OR**, applied to both the history side and the target side, so a
caller passing `neutral_site=False` for a Paris game cannot reintroduce the bug.

## The seal on the holdout

Amendment 5e: *"2025-26 labels reach the model only through a single function that
refuses a dirty tree, refuses a second call, and commits a marker with the frozen commit
hash and time."* That is `holdout.open_holdout`, and there is no second function and no
keyword that relaxes it.

**Why a clean tree is the right proxy for "the model is frozen."** Nothing can inspect a
model and certify it frozen. What *is* checkable is that the working tree matches a
commit and that the hash goes into the marker before any label is returned. Whatever is
committed at that instant IS the frozen model — the same argument Amendment 5b uses for
the Elo constants, where git history is the proof of order. `--porcelain` counts
untracked files as dirty, which matters: an untracked scratch model is exactly what
would not be in the recorded commit.

**It fails closed.** The marker is written and committed *before* the labels are
returned. If the commit fails, the caller gets nothing and the half-written marker
leaves the tree dirty, so the next attempt refuses on the dirty-tree check rather than
quietly succeeding. There is a test for that path.

**The marker pins what was let out, not merely that something was**: the frozen commit,
the UTC time, the required reason, the game count, and a SHA-256 over the released
`(sport, season, game_id, y)` tuples.

**`assert_dev_only` is the guard that will actually catch something.** Nobody
accidentally calls `open_holdout`; what happens is a frame assembled without a season
filter. Model code calls `assert_dev_only(rows)` on whatever it is about to fit or tune
on, and gets the count and the first offending game id.

**What is NOT sealed, stated plainly because getting this wrong cuts both ways.** The
seal is on the *model's* access to 2025-26 outcomes. The census, the validation gate and
headline 2 read both seasons by design — headline 2 is a measurement of the market's own
calibration, pre-registered in section 8 to stratify *within* season, and it was
published in week 6 before any model existed. Treating the seal as global would void a
published result; treating it as looser than it is would give a false sense that the
model is sealed when it is not.

A test in `tests/test_holdout.py` asserts this repository has **no** `HOLDOUT_OPENED.json`.
When that test fails, either week 9 happened or something opened the seal by accident.
