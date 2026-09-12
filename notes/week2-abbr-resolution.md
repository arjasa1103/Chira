# Week 2 — resolving schedule abbreviations to slug abbreviations

The week-1 map (`data/abbr_map.json`) was unusable for the census for two
reasons found during the `/review` pass and fixed here.

1. **Wrong direction.** It maps `{slug_abbr: nickname}`. Slug construction needs
   `{schedule_abbr: slug_abbr}`. Nothing in the codebase read the file.
2. **Incomplete.** It was built by paginating Gamma, and Gamma's offset ceiling
   made it return **0 of 30 NBA teams for 2025-26** while finding 32/32 NHL from
   identical windows.

`resolve.py` replaces it with a schedule-driven resolver that **confirms** every
mapping against the market's own `outcomes` labels. `data/abbr_map.json` is now
only a prior into it.

## Result: 124 of 124 team-seasons resolved, 91 probes total

| Season | Sport | Teams | Probes |
|---|---|---|---|
| 2024-25 | NBA | 30/30 | 26 |
| 2024-25 | NHL | 32/32 | 19 |
| 2025-26 | NBA | 30/30 | 26 |
| 2025-26 | NHL | 32/32 | 20 |

NBA needs no translation at all: the schedule abbreviation is the slug
abbreviation for all 30 teams in both seasons. NHL needs seven, identical across
both seasons:

```
cgy -> cal    mtl -> mon    njd -> nj    sjs -> sj
tbl -> tb     uta -> utah   vgk -> las
```

**`vgk -> las` was not in any document.** Verified directly: `nhl-nyr-las-2025-01-11`
hits with outcomes `["Rangers", "Golden Knights"]` while `nhl-nyr-vgk-...` and
`nhl-nyr-vegas-...` both miss. Without it, all 164 Vegas games across the two
seasons would have been recorded as "no market exists" — about 3% of the sample,
and concentrated in one team, which is exactly the shape of error that moves the
coverage chart deciding the primary sport.

## Three things each cost a failed run

1. **Probe mid-season, not in date order.** Probing in date order resolved
   **0 of 32** NHL teams for 2024-25: the entire attempt budget went to
   early-October games, and Polymarket's NHL coverage does not start at the
   season opener. `probe_order` now works outward from the season midpoint.
2. **Match the place name as well as the nickname.** Utah's schedule nickname is
   `Mammoth` in 2025-26 and the market label is `Utah`. Nickname-only matching
   resolved Utah in one season and missed it in the other. Place names are only
   accepted when unique in the league, because "Los Angeles" covers two NBA
   teams and a place-level match there could confirm a slug with the two sides
   **swapped** — which does not crash, it mirrors the calibration curve.
3. **Only an unresolved side spends attempt budget.** Charging a resolved
   opponent starved teams whose games all faced already-confirmed opponents.

## What was NOT established

- **Only the two usable seasons.** 2023-24's documented `no` (New Orleans) is
  not re-verified here; that season is excluded from the project.
- **Conventions are stable within a season, as far as this probe can see.** The
  resolver confirms a team from one or two games and then trusts the mapping for
  its other ~80. A mid-season convention change would be seen as a run of
  `no_market` misses for one team, which the coverage-by-week chart would show.
- **Playoffs, preseason, All-Star, and the 4 Nations Face-Off** are untested.
  The week-1 map contains `cannhl -> Canada` and NBA All-Star entries
  (`cgs`, `crs`, `kys`, `sog`), so those slugs exist; they are not in scope.
