"""The GBM benchmark ceiling (T17).

T17 exists because *"the interpretability veto is an assertion, not a
measurement"*. PLAN Phase 4 chose a hierarchical logistic over a black box on
interpretability grounds; this turns the cost of that choice into a number.

**The GBM is never shipped.** It is fitted on the same rows, with the same
features, scored by the same rolling origin, and then reported. Nothing
downstream imports a prediction from it, and nothing in the artifact's
pipeline depends on it.

**It is deliberately a strong baseline, not a token one.** An under-powered
ceiling would make interpretability look free, which is the exact assertion
T17 was raised to replace. So this uses scikit-learn's
`HistGradientBoostingClassifier` at its defaults rather than a hand-rolled
booster, and the only tuning is an early-stopping split taken from the
TRAINING fold -- never from the block being predicted.

**It sees exactly what the model sees.** Same design matrix: the frozen Elo
difference and the same schedule features, standardised with the same frozen
statistics. A ceiling fitted on extra inputs would measure the inputs, not
the functional form, and the comparison would say nothing about
interpretability.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .holdout import assert_dev_only
from .model import Design, build_design, dev_medians, fold_slices

# Defaults, stated rather than tuned. `early_stopping` carves a validation
# slice out of the TRAINING rows; `random_state` makes the fold reproducible.
GBM_KW: dict = {
    "max_iter": 400,
    "learning_rate": 0.05,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 20,
    "l2_regularization": 1.0,
    "early_stopping": True,
    "validation_fraction": 0.15,
    "n_iter_no_change": 25,
    "random_state": 0,
}


@dataclass
class CeilingFold:
    origin: str
    n_train: int
    n_test: int
    game_ids: list[str]
    p: np.ndarray
    y: np.ndarray
    n_iter: int


def _matrix(design: Design) -> np.ndarray:
    """The model's own covariates, nothing more: Elo plus the features."""
    return np.column_stack([design.rating, design.features])


def fit_predict(train: Design, test: Design, **kw) -> tuple[np.ndarray, int]:
    from sklearn.ensemble import HistGradientBoostingClassifier

    gbm = HistGradientBoostingClassifier(**{**GBM_KW, **kw})
    gbm.fit(_matrix(train), train.y.astype(int))
    p = gbm.predict_proba(_matrix(test))[:, 1]
    return p, int(gbm.n_iter_)


def rolling_origin_ceiling(rows: list[dict], *, sport: str,
                           origins: tuple[str, ...] | None = None,
                           **kw) -> list[CeilingFold]:
    """The GBM under the SAME folds the model is evaluated on.

    Any other split would compare two things at once. The scaler and the fill
    medians come from each fold's training games, exactly as `rolling_origin`
    does, so neither model sees a statistic from the block it predicts.
    """
    from .model import ROLLING_ORIGINS

    origins = origins or ROLLING_ORIGINS
    rows = [r for r in rows if r["sport"] == sport]
    if not rows:
        raise ValueError(f"no {sport} rows")
    assert_dev_only(rows, what=f"{sport} ceiling rows")
    out = []
    for origin, _, train, test in fold_slices(rows, origins, sport=sport):
        med = dev_medians(train)
        d_train = build_design(train, sport=sport, medians=med)
        d_test = build_design(test, sport=sport, scaler=d_train.scaler,
                              medians=med)
        p, n_iter = fit_predict(d_train, d_test, **kw)
        out.append(CeilingFold(origin=origin, n_train=len(train),
                               n_test=len(test),
                               game_ids=list(d_test.game_ids), p=p,
                               y=d_test.y, n_iter=n_iter))
    return out


def pooled_ceiling(folds: list[CeilingFold]
                   ) -> tuple[np.ndarray, np.ndarray, list[str]]:
    return (np.concatenate([f.p for f in folds]),
            np.concatenate([f.y for f in folds]),
            [g for f in folds for g in f.game_ids])
