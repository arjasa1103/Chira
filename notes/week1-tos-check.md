# E18 — Polymarket ToS check (week 1)

**Status: UNRESOLVED. Requires a human to read the actual Terms of Use.**

## What was attempted

1. `https://docs.polymarket.com/api-reference/markets/get-prices-history` — fetched
   successfully. Carries **no** redistribution terms, license, or attribution requirement
   for the data. The `license: MIT` field on that page applies to the OpenAPI spec, not to
   market data. **Useful byproduct: `fidelity` is documented as "Accuracy of the data
   expressed in minutes. Default is 1 minute."** That closes the plan's open question about
   the unit.
2. `https://polymarket.com/tos` — renders client-side; the fetch returned the SPA shell,
   navigation, and JSON-LD only. No substantive terms text.
3. Web search — returned summaries describing restrictive language (no reproducing,
   reselling, scraping, republishing without written consent; limited non-commercial
   license). **These summaries cannot be trusted for this purpose:** the result set mixed
   Polymarket's own page with third-party sites (`polymarket.guide`, a copy-trade service,
   a Telegram-bot vendor) that have their own unrelated terms. Attributing those clauses to
   Polymarket would be unfounded.

## What this gates

**Only E1** (publish the census as a public dataset release). It does not affect the
census itself, either headline result, the model, or any chart. Weeks 1-4 are unaffected;
the decision is needed before weeks 5-6.

## Recommended de-risking (does not need the ToS answer)

Split the release so the valuable part carries no redistribution question:

- **Publish the collector code plus a one-command reproduction script.** Anyone can
  regenerate the census from the public API themselves. For a portfolio artifact this is
  arguably *stronger* than shipping a data blob, because it demonstrates the engineering
  rather than the output.
- **Publish derived aggregates only** — calibration curves, per-stratum statistics, bin
  counts, Brier decompositions. These are research results, not a republication of the
  underlying price series.
- **Hold the raw minute-level series back** unless and until the ToS is confirmed to permit
  redistribution.

This preserves headline 2 and the "an artifact exists by end of week 6" gate with no legal
exposure. If the ToS later turns out to permit redistribution, adding the raw series is a
one-line release change.

## Action for the user

Open `https://polymarket.com/tos` in a normal browser and search for: `scrap`, `redistribut`,
`republish`, `commercial`, `intellectual property`, `data`. Five minutes. Record the verdict
here.
