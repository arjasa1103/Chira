-- Census store. One file, four tables, no growth beyond the census.
--
-- The design rule here is the reconciliation identity:
--
--     scheduled == priced + misses
--
-- Every scheduled game lands in EXACTLY ONE of `priced` or `misses`, both keyed
-- by (sport, season, game_id). A game that is silently in neither is the
-- failure mode this whole store exists to make impossible: the coverage chart
-- that gates the project is a ratio, and a lost denominator row moves it
-- without anything looking broken.
--
-- Primary keys make the census idempotent: a resumed run REPLACEs the rows it
-- re-fetches rather than appending a second copy.
--
-- `run_id` on every data row answers "which rows predate the fix?". A census is
-- written incrementally across multi-day resumable runs and `settled_game_ids`
-- permanently skips anything already settled, so without it a finished store is
-- an unlabelled mixture of however many code versions the run spanned.
--
-- This file is applied as CREATE TABLE IF NOT EXISTS, so it describes a FRESH
-- store only. Changes to an existing store go through store._MIGRATIONS.

CREATE TABLE IF NOT EXISTS games (
    sport         TEXT    NOT NULL,
    season        TEXT    NOT NULL,
    game_id       TEXT    NOT NULL,
    et_date       DATE    NOT NULL,
    away          TEXT    NOT NULL,
    home          TEXT    NOT NULL,
    away_pts      INTEGER,
    home_pts      INTEGER,
    winner        TEXT    NOT NULL,   -- 'away' | 'home', from the LEAGUE, never the market
    neutral_site  BOOLEAN DEFAULT FALSE,
    run_id        TEXT,
    PRIMARY KEY (sport, season, game_id)
);

CREATE TABLE IF NOT EXISTS priced (
    sport            TEXT    NOT NULL,
    season           TEXT    NOT NULL,
    game_id          TEXT    NOT NULL,
    slug             TEXT    NOT NULL,
    convention       TEXT    NOT NULL,   -- 'et' | 'et_plus_1', which date convention hit
    away_nickname    TEXT,
    home_nickname    TEXT,
    p_home_close     DOUBLE  NOT NULL,
    p_home_t1h       DOUBLE,
    n_pre_tipoff     INTEGER NOT NULL,
    secs_before_tip  INTEGER NOT NULL,
    stale_flat_run   BOOLEAN,
    complement_sum   DOUBLE,
    complement_ok    BOOLEAN,
    market_winner    TEXT,               -- 'away' | 'home' | NULL, from outcomePrices
    label_agreement  TEXT    NOT NULL,   -- 'agree' | 'disagree' | 'unresolved' (E1)
    volume           DOUBLE,
    game_start_time  TIMESTAMPTZ,
    run_id        TEXT,
    PRIMARY KEY (sport, season, game_id)
);

CREATE TABLE IF NOT EXISTS misses (
    sport      TEXT NOT NULL,
    season     TEXT NOT NULL,
    game_id    TEXT NOT NULL,
    reason     TEXT NOT NULL,   -- constants.MISS_REASONS; enforced in store.py
    attempted  TEXT NOT NULL,   -- JSON array of every slug tried, so "slug variant
                                -- not tried" is distinguishable from "no market"
    detail     TEXT,
    run_id        TEXT,
    PRIMARY KEY (sport, season, game_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    manifest     TEXT NOT NULL,   -- JSON: season windows, abbr-map fingerprint, versions
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS meta (
    k TEXT NOT NULL,
    v TEXT NOT NULL,
    PRIMARY KEY (k)
);
