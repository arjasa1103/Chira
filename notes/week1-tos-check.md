# E18 — Polymarket ToS check

**Status: RESOLVED 2026-09-22.** The user read the Terms of Use and supplied the relevant
clauses. **Decision: publish the collector code, a reproduction path and the writeup with its
charts. No dataset release.** T11/E1 are rescoped accordingly.

*Not legal advice. This is a careful reading of the clauses below by the people building the
project, recorded so the decision is auditable.*

## The clauses that matter

Three prohibitions, quoted from the Terms of Use:

1. > Use any data mining tools, robots, crawlers, or similar data gathering and extraction
   > tools to scrape or otherwise remove data from the Site, any other Interface, or Features;

2. > Access or use any data, content, or information contained on our Site, any Interface or
   > Features directly or through an API, or any other means, including on-chain, whether in
   > raw, derived, aggregated, or anonymized form (the "Data") if you are (i) a non-retail,
   > professional entity that engages in capital markets activities (e.g., brokerage, market
   > making, proprietary trading, index calculation, or ETF issuance) [...] (each, a "Capital
   > Market Client"), or (ii) a market data distributor, in each case unless otherwise agreed
   > to in writing by us;

3. > Sell, resell, sublicense, redistribute, or otherwise commercially exploit the Data to any
   > Capital Market Client or market data distributor, unless otherwise agreed to in writing
   > by us

## What they mean for this project

**Clause 2 does not bite on who we are.** It restricts *access* by non-retail professional
capital-markets entities — broker-dealers, hedge funds, prop trading firms, "financial
technology companies" — and by market data distributors. A semester calibration study is
none of those.

**Clause 1 is the one that is genuinely unsettled, and the earlier "we don't scrape" reading
is too comfortable.** The census is an automated data-gathering program that made ~16,400
requests. That is what "data mining tools, robots [...] data gathering and extraction tools"
describes, on a plain reading. The counter-argument is that we used documented public API
endpoints under a rate limiter rather than scraping the website — but clause 2 says
"directly or **through an API**", so the terms clearly contemplate API access as in scope for
the Data rules.

**Whether clause 1 reaches the API depends on defined terms we have not read.** "Site",
"Interface" and "Features" are capitalised, so they are defined elsewhere in the document.
If "Interface" includes the public API, clause 1 covers this collection directly. That
question is open and is the thing to check if the stakes ever rise above a course project.

**Clause 3 is narrower than a blanket redistribution ban**, and this is the useful part: it
prohibits redistributing Data *to a Capital Market Client or market data distributor*. It
does not prohibit publication generally. But a public GitHub release cannot choose its
recipients.

## The finding that changed the plan

Week 1's recommended mitigation was "publish derived aggregates only — these are research
results, not a republication of the underlying price series." **That reasoning does not
survive the actual text.** Clause 2 defines Data as information "whether in **raw, derived,
aggregated, or anonymized** form". The definition is written specifically to cover aggregates,
so "it's only aggregates" is not the safe harbour week 1 assumed it was.

## Decision

**Publish:** the collector and pipeline code, a reproduction path so anyone can regenerate the
census from the public API themselves, and the writeup with its charts and the statistics
behind them.

**Do not publish:** the census as a dataset — not the raw minute-level series, and not an
aggregate dataset release either. T11/E1 become "regenerate it yourself", which for a
portfolio artifact demonstrates the engineering rather than the output.

**Already committed and kept:** `docs/charts/*.png`, `chart-data.json` and `headline2.json`.
These are the figures and statistics *of the writeup* — calibration curves, bin counts, Murphy
decompositions, per-stratum slopes, and the volume medians that define the strata. They are
published as research results, which is what a paper's tables are, and they are deliberately
not framed or distributed as a dataset. No raw price series is committed; `data/` and
`.http-cache/` stay gitignored.

**Not pursued for now:** both clauses say "unless otherwise agreed to in writing by us", so
written permission is the mechanism the terms themselves point to, and an academic request
would be cheap. It is not on the critical path, because the December deliverable no longer
depends on a dataset release. If permission is ever granted, adding the series back is a
release change, not a redesign.

## Licensing that follows from this

MIT for the code, CC BY 4.0 for the writeup, notes and figures (`LICENSE` and
`LICENSE-docs.md`). Neither licence purports to grant rights over Polymarket's data, because
the project does not distribute it.

## Week-1 record, kept

What was attempted in week 1, when this was left unresolved:

1. `https://docs.polymarket.com/api-reference/markets/get-prices-history` — fetched
   successfully. Carries **no** redistribution terms, license, or attribution requirement
   for the data. The `license: MIT` field on that page applies to the OpenAPI spec, not to
   market data. **Useful byproduct: `fidelity` is documented as "Accuracy of the data
   expressed in minutes. Default is 1 minute."** That closed the plan's open question about
   the unit.
2. `https://polymarket.com/tos` — renders client-side; the fetch returned the SPA shell,
   navigation, and JSON-LD only. No substantive terms text. **This is why it needed a human
   with a browser**, and it is how the check stayed open from week 1 to week 5.
3. Web search — returned summaries describing restrictive language (no reproducing,
   reselling, scraping, republishing without written consent; limited non-commercial
   license). **These summaries could not be trusted for this purpose:** the result set mixed
   Polymarket's own page with third-party sites (`polymarket.guide`, a copy-trade service,
   a Telegram-bot vendor) that have their own unrelated terms. Attributing those clauses to
   Polymarket would have been unfounded — and note the real clauses turned out to be
   narrower and more specific than those summaries suggested.
