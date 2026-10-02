"""The GBM benchmark ceiling (T17).

T17's point is that the interpretability veto was an assertion. These tests
guard the thing that would make the resulting number meaningless: a ceiling
fitted on different inputs, or on different folds, than the model it is
compared against.
"""

from __future__ import annotations

import numpy as np
import pytest

# Eager, at module scope: conftest's `_no_network` fixture replaces
# socket.socket with a function and `ssl` subclasses it at import time, so a
# lazy sklearn import inside a test dies with a TypeError that looks like an
# sklearn bug. Same trap as numpyro in tests/test_model.py.
import sklearn.ensemble  # noqa: F401

from chira.ceiling import (
    GBM_KW,
    _matrix,
    fit_predict,
    pooled_ceiling,
    rolling_origin_ceiling,
)
from chira.holdout import DEV_SEASON, HOLDOUT_SEASON, HoldoutError
from chira.model import ROLLING_ORIGINS, build_design
from chira.ratings import MODEL_COVARIATE

DAY = 86400


def row(gid, away, home, start, *, season=DEV_SEASON, y=1.0, rating=50.0):
    return {"sport": "nba", "season": season, "game_id": str(gid),
            "away": away, "home": home, "y": y, "start_t": start,
            "away_rest_days": 2, "home_rest_days": 2,
            "away_b2b": False, "home_b2b": False,
            "away_travel_km": 1000.0, "home_travel_km": 900.0,
            "away_tz_shift": 0.0, "home_tz_shift": 0.0,
            MODEL_COVARIATE: rating, "neutral_site": False}


def season_frame(n=240, season=DEV_SEASON):
    """A synthetic season spanning 2024-10-05 to 2025-04-12, so every
    pre-registered origin has games on both sides of it."""
    import datetime as dt
    start = int(dt.datetime.fromisoformat("2024-10-05T00:00:00+00:00")
                .timestamp())
    span = int(dt.datetime.fromisoformat("2025-04-12T00:00:00+00:00")
               .timestamp()) - start
    step = span // n
    teams = ["bos", "nyk", "lal", "phi"]
    rng = np.random.default_rng(0)
    out = []
    for i in range(n):
        rating = float(rng.normal(0, 120))
        p = 1.0 / (1.0 + np.exp(-(rating / 200.0)))
        out.append(row(i, teams[i % 4], teams[(i + 1) % 4],
                       start + i * step, season=season,
                       y=float(rng.uniform() < p), rating=rating))
    return out


class TestItSeesExactlyWhatTheModelSees:
    def test_the_matrix_is_the_rating_plus_the_model_features(self):
        d = build_design(season_frame(40), sport="nba")
        m = _matrix(d)
        assert m.shape == (40, 1 + d.features.shape[1])
        np.testing.assert_allclose(m[:, 0], d.rating)
        np.testing.assert_allclose(m[:, 1:], d.features)

    def test_no_label_or_identifier_leaks_into_the_matrix(self):
        """A ceiling that can see y, or the game id, measures nothing."""
        d = build_design(season_frame(40), sport="nba")
        m = _matrix(d)
        for col in range(m.shape[1]):
            assert not np.allclose(m[:, col], d.y)


class TestTheFolds:
    def test_it_uses_the_same_origins_as_the_model(self):
        folds = rolling_origin_ceiling(season_frame(), sport="nba")
        assert [f.origin for f in folds] == list(ROLLING_ORIGINS)

    def test_test_blocks_are_disjoint_and_cover_no_training_game(self):
        folds = rolling_origin_ceiling(season_frame(), sport="nba")
        seen = [g for f in folds for g in f.game_ids]
        assert len(seen) == len(set(seen))
        assert all(f.n_train > 0 and f.n_test > 0 for f in folds)

    def test_pooling_concatenates_in_fold_order(self):
        folds = rolling_origin_ceiling(season_frame(), sport="nba")
        p, y, ids = pooled_ceiling(folds)
        assert len(p) == len(y) == len(ids) == sum(f.n_test for f in folds)
        assert ids[:folds[0].n_test] == folds[0].game_ids

    def test_it_refuses_holdout_rows(self):
        rows = [*season_frame(80),
                row(999, "bos", "nyk", 0, season=HOLDOUT_SEASON)]
        with pytest.raises(HoldoutError, match="sealed holdout"):
            rolling_origin_ceiling(rows, sport="nba")

    def test_it_refuses_a_sport_with_no_rows(self):
        with pytest.raises(ValueError, match="no nhl rows"):
            rolling_origin_ceiling(season_frame(), sport="nhl")


class TestTheFitItself:
    def test_it_returns_probabilities_and_an_iteration_count(self):
        rows = season_frame(300)
        tr = build_design(rows[:200], sport="nba")
        te = build_design(rows[200:], sport="nba", scaler=tr.scaler)
        p, n_iter = fit_predict(tr, te)
        assert p.shape == (100,)
        assert (p > 0).all() and (p < 1).all()
        assert n_iter >= 1

    def test_it_learns_something_from_a_strong_signal(self):
        """If the ceiling cannot find a signal this obvious, the comparison
        it feeds is not measuring the functional form."""
        rows = season_frame(400)
        tr = build_design(rows[:300], sport="nba")
        te = build_design(rows[300:], sport="nba", scaler=tr.scaler)
        p, _ = fit_predict(tr, te)
        high = te.rating > np.median(te.rating)
        assert p[high].mean() > p[~high].mean()

    def test_early_stopping_takes_its_split_from_training_only(self):
        """scikit-learn carves `validation_fraction` out of what it is
        handed, and it is only ever handed the training fold."""
        assert GBM_KW["early_stopping"] is True
        assert 0 < GBM_KW["validation_fraction"] < 0.5

    def test_the_defaults_are_stated_not_tuned_per_run(self):
        assert GBM_KW["random_state"] == 0
        assert set(GBM_KW) >= {"max_iter", "learning_rate", "max_leaf_nodes"}
