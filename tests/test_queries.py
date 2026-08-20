"""The analysis SQL in queries/.

These run the real .sql files, so a renamed column or a typo fails CI rather
than surfacing the next time the queries are run by hand.
"""

import pytest

from augmentstats.collect.ingest import ingest_game
from augmentstats.db import PROJECT_ROOT, get_connection
from tests.factories import make_game, make_participant

QUERY_DIR = PROJECT_ROOT / "queries"
QUERY_FILES = sorted(QUERY_DIR.glob("*.sql"))


def test_query_directory_is_not_empty():
    """Guard against the glob silently finding nothing and vacuously passing."""
    assert QUERY_FILES, f"no .sql files found in {QUERY_DIR}"


@pytest.mark.parametrize("sql_path", QUERY_FILES, ids=lambda p: p.name)
def test_query_parses_and_runs(sql_path, conn):
    """Executes against an empty schema. Catches typos and renamed columns."""
    conn.execute(sql_path.read_text(encoding="utf-8")).fetchall()


def _populate(conn):
    """Two games where champion 100 wins once and loses once with augment 101."""
    for game_id, win in [(1, True), (2, False)]:
        game = make_game(
            game_id=game_id,
            participants=[make_participant(1, champion_id=100, win=win, augments=(101, 102))],
        )
        ingest_game(conn, game, "2026-08-20T12:00:00+00:00")

    conn.execute(
        "INSERT INTO champions (champion_id, api_id, name) VALUES (?, ?, ?)",
        (100, "Ahri", "Ahri"),
    )
    conn.executemany(
        "INSERT INTO augments (augment_id, api_name, name, rarity) VALUES (?, ?, ?, ?)",
        [(101, "AugA", "Augment A", "Silver"), (102, "AugB", "Augment B", "Gold")],
    )
    conn.commit()


def test_champion_augment_winrates_computes_the_expected_rate(db_path):
    conn = get_connection(db_path)
    _populate(conn)

    sql = (QUERY_DIR / "champion_augment_winrates.sql").read_text(encoding="utf-8")
    rows = {r["augment"]: r for r in conn.execute(sql)}

    assert rows["Augment A"]["champion"] == "Ahri"
    assert rows["Augment A"]["picks"] == 2
    assert rows["Augment A"]["wins"] == 1
    assert rows["Augment A"]["win_rate_pct"] == 50.0
    conn.close()


def test_single_pick_pairs_are_excluded_by_the_having_threshold(db_path):
    """champion_augment_winrates has HAVING picks >= 2, so a lone pick drops out."""
    conn = get_connection(db_path)
    _populate(conn)
    game = make_game(
        game_id=3,
        participants=[make_participant(1, champion_id=100, win=True, augments=(999,))],
    )
    ingest_game(conn, game, "2026-08-20T12:00:00+00:00")
    conn.execute(
        "INSERT INTO augments (augment_id, api_name, name, rarity) VALUES (?, ?, ?, ?)",
        (999, "AugC", "Augment C", "Prismatic"),
    )
    conn.commit()

    sql = (QUERY_DIR / "champion_augment_winrates.sql").read_text(encoding="utf-8")
    names = {r["augment"] for r in conn.execute(sql)}
    assert "Augment C" not in names, "a single pick should not clear HAVING picks >= 2"
    conn.close()


def test_missing_reference_rows_silently_drop_results(db_path):
    """A gotcha worth pinning: the queries INNER JOIN augments and champions.

    If refresh-augments / refresh-champions has not been run, picks vanish from
    every report rather than showing up with a blank name. Any read layer built
    on these queries needs to know that.
    """
    conn = get_connection(db_path)
    for game_id, win in [(1, True), (2, False)]:
        game = make_game(
            game_id=game_id,
            participants=[make_participant(1, champion_id=100, win=win, augments=(101,))],
        )
        ingest_game(conn, game, "2026-08-20T12:00:00+00:00")
    conn.commit()  # deliberately no augments/champions rows

    sql = (QUERY_DIR / "champion_augment_winrates.sql").read_text(encoding="utf-8")
    assert conn.execute(sql).fetchall() == []

    picks = conn.execute("SELECT COUNT(*) FROM participant_augments").fetchone()[0]
    assert picks == 2, "the picks exist; only the join hides them"
    conn.close()
