# Prior art, and what this project adds

T12. Four sources were named in the planning documents and none were cited; this is that
section. Two were read in full, one is blocked to automated access, one could not be found,
and **one turns out to contradict a claim this project's own plan made about it.** Each entry
says which, because a prior-art section whose citations were never opened is worse than none.

## 1. Le (2026), "Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets"

arXiv:[2602.19520](https://arxiv.org/abs/2602.19520), stat.AP. Submitted 23 Feb 2026, revised
4 Aug 2026 (v2). **Read 2026-09-25.**

This is the closest prior art by a wide margin, and closer than the plan realised. From the
abstract: 353 million trades across 429,000 binary contracts on Kalshi and Polymarket,
measuring how calibration varies with **event domain, time-to-resolution and trade size**.
It decomposes **cell-level logistic recalibration slopes** — the same estimand this project
calls the Cox slope — and reports:

- persistent **underconfidence in political markets, where prices compress toward 50%**, as
  the most robust pattern, replicating on Polymarket;
- large political trades on Kalshi associated with further compression, **"a
  calibration-slope gap of roughly one-half"**, surviving market- and event-clustered
  bootstraps but **not robust on Polymarket**;
- a Bayesian measurement-error model indicating that, under conservative event-clustered
  standard errors, **roughly half of the raw slope variation reflects estimation noise**;
- the conclusion that "calibration is therefore conditional: a price's meaning depends on
  what, when and how much is traded."

**What this project adds.** A different domain (NBA and NHL game outcomes, not politics), a
different size axis (terminal per-market volume, not trade size), a per-game grain with
labels taken from the leagues rather than from the venue being measured, and a
pre-registered design in which the confound between the size axis and season phase was
measured and removed before the test was run (Amendment 3a). Le finds the trade-size
compression **not robust on Polymarket**; this project finds a liquidity slope gap of
**+0.812 [+0.618, +1.033]** on Polymarket NBA moneylines, which is a Polymarket result on an
axis Le's Polymarket arm did not settle.

**What this project must take from it, and does.** Le's noise result is a direct warning about
our own interval: half of raw slope variation being estimation noise was established *under
event-clustered standard errors*, and our bootstrap resamples games independently. Outcomes
cluster by date and team, so an independent-game bootstrap can be optimistic. That is why the
writeup reports a **date-clustered bootstrap beside the pre-registered one** and treats the
wider of the two as the honest interval. The comparison exists because this paper was read.

## 2. Galekwa, Tshimula, Tajeuna and Kyandoghere (2024), "A Systematic Review of Machine Learning in Sports Betting: Techniques, Challenges, and Future Directions"

arXiv:[2410.21484](https://arxiv.org/abs/2410.21484), cs.LG. Submitted 28 Oct 2024.
**Read 2026-09-25.**

A review of ML across soccer, basketball, tennis and cricket: support vector machines, random
forests and neural networks applied to historical data, in-game statistics and real-time
information, aimed at "optimiz[ing] betting strategies and identify[ing] value bets,
ultimately improving profitability", dynamic odds adjustment and risk management for
bookmakers, plus anomaly detection for fraud. It names data quality, real-time
decision-making and the unpredictability of outcomes as open challenges.

**What this project adds, by refusing the review's objective.** This literature optimises
profit; Chira scores **calibration**, and contains no staking system, no odds-setting and no
bet placement (PLAN.md, "Out of scope"). The market here is the *benchmark*, not the thing to
beat: the question is how well a price-free model matches a real-money market's probabilities
and where that market is itself miscalibrated. The review's framing is the reason this
project states "the claim is calibration, not profit" in its first paragraph — the adjacent
literature is overwhelmingly about returns, and a calibration result read as a betting edge
would be a misreading.

## 3. Wheatcroft (2019), "Evaluating probabilistic forecasts of football matches: The case against the Ranked Probability Score"

arXiv:[1908.08980](https://arxiv.org/abs/1908.08980). Submitted 23 Aug 2019.
**Read 2026-09-25 — and it does not say what this project's plan said it says.**

PLAN.md cites "Wheatcroft 2022" for the proposition that the literature "recommends
Brier/log-loss over RPS". The paper does argue against the RPS: it disputes that sensitivity
to distance adds anything, and finds that in two simulation experiments **the ignorance score
— which is local, i.e. the logarithmic score — outperforms *both* the RPS *and* the Brier
score**, "casting doubt on the value of non-locality and sensitivity to distance as
properties of scoring rules in this context".

So the citation half-holds and half-inverts:

- **Holds:** RPS is not the right scoring rule here, and this project does not use it.
- **Inverts:** the paper's preferred rule is the log score, while
  [PREREGISTRATION.md](../PREREGISTRATION.md) section 3 makes **Brier primary** and log loss
  secondary with no hypothesis test attached.

**The pre-registered choice stands, with its reason stated rather than a citation
misquoted.** Section 3's argument for Brier primary is boundedness: unclipped log loss is
unbounded, so a single mis-joined label at an extreme price could silently decide the
headline, which is a real hazard in a pipeline whose labels come from a third party. Both are
reported for every result. The honest position is that this paper would rank them the other
way round, and a reader who prefers the log score can read it off the same tables. Two smaller
corrections: the year is 2019 for the preprint read here, not 2022, and the paper is about
three-way football outcomes while this project scores two-way moneylines, where locality and
distance-sensitivity arguments are weaker.

## 4. Reichenbach and Walther, "Accuracy, Skill, and Bias on Polymarket" (SSRN 5910522)

**NOT VERIFIED.** `papers.ssrn.com` returned HTTP 403 with a Cloudflare content-protection
notice for automated access on 2026-09-25. The block was respected rather than worked around,
so nothing in this project cites a finding from this paper. It is named here because the
planning documents named it, and it is on its face the most directly comparable work
(accuracy, skill and bias, on Polymarket specifically).

**Action before v2:** a human should open it and either record its claims here or drop the
citation. If it already reports a liquidity-conditioned calibration result on Polymarket
sports markets, that materially changes how this project's contribution should be described.

## 5. Wilkens (2026), "Can simple models predict football and beat the odds?"

**NOT FOUND.** No arXiv match for the title or for the author in the relevant categories
(searched 2026-09-25). It may exist on SSRN or in a journal, both outside what could be
checked here. Recorded as a citation this project cannot currently substantiate. Its likely
relevance is to headline 1 (a simple model against the market) rather than to headline 2, so
it is not load-bearing for artifact v1.

## Data sources this project did not reuse

Two bulk Polymarket datasets were identified during planning and **not evaluated**:
`manja316/polymarket-historical-data` (13,964 markets, 10.8M price records) and
`SII-WANGZJ/Polymarket_data` (107GB, 1.1B records, 268K markets). They are third-party and
unvetted, so provenance, per-game NBA/NHL coverage and fidelity are all unknown, which is why
the census was collected first-hand. They remain a cheap **cross-validation** of it rather
than a replacement, and that check (T16) is still open.

## Where this leaves the contribution

Stated narrowly, because the honest version is narrow:

1. **A liquidity-conditioned calibration result on Polymarket sports moneylines**, on the same
   estimand as Le (2026) but a different domain and size axis, on the platform where Le's
   trade-size result did not hold.
2. **A pre-registered design whose confounds were measured, not asserted** — the volume/season-phase
   correlation removed before testing (Amendment 3a), the price-range artifact tested by
   caliper matching, the event-volume proxy withdrawn on measurement (Amendment 4).
3. **Per-cell noise floors simulated from the census's own price pool**, which is what makes
   "this cell is miscalibrated" a falsifiable statement at n≈225 rather than a plotted wiggle.
4. **A census whose collection is reproducible from public endpoints**, with every miss
   classified and the reconciliation identity enforced, rather than a dataset of unknown
   provenance.

Not claimed: novelty of the estimand, novelty of the question, or that any of this beats a
market.
