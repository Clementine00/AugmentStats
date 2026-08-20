"""Schema creation and the ad-hoc migration path in db.py."""

import sqlite3

from augmentstats.db import ITEM_COLUMNS, get_connection, init_db

EXPECTED_TABLES = {
    "games",
    "teams",
    "participants",
    "participant_augments",
    "augments",
    "champions",
}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_init_db_creates_every_table(db_path):
    conn = get_connection(db_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= names
    conn.close()


def test_init_db_is_idempotent(db_path):
    """Running init-db twice is documented as safe -- it also runs migrations."""
    init_db(db_path)
    init_db(db_path)

    conn = get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0
    conn.close()


def test_migrate_adds_item_columns_and_backfills_patch(tmp_path):
    """An old-shaped database gains item0..item6 and a backfilled patch column.

    The old shape is written by hand rather than derived from SCHEMA, so this
    test still means something if SCHEMA changes.
    """
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE games (
            game_id INTEGER PRIMARY KEY,
            game_version TEXT,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE participants (
            game_id INTEGER,
            participant_id INTEGER,
            champion_id INTEGER,
            PRIMARY KEY (game_id, participant_id)
        );
        """
    )
    old.execute(
        "INSERT INTO games (game_id, game_version, imported_at) VALUES (?, ?, ?)",
        (1, "16.15.801.3452", "2026-08-20T00:00:00+00:00"),
    )
    old.execute(
        "INSERT INTO games (game_id, game_version, imported_at) VALUES (?, ?, ?)",
        (2, None, "2026-08-20T00:00:00+00:00"),
    )
    old.commit()
    old.close()

    init_db(path)

    conn = get_connection(path)
    assert set(ITEM_COLUMNS) <= _columns(conn, "participants")
    assert "patch" in _columns(conn, "games")

    rows = dict(conn.execute("SELECT game_id, patch FROM games"))
    assert rows[1] == "16.15", "patch should be backfilled from game_version"
    assert rows[2] is None, "an unparseable version should backfill as NULL, not crash"
    conn.close()


def test_foreign_keys_are_enforced(db_path):
    """get_connection turns on foreign_keys; a dangling child row must fail."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO participants (game_id, participant_id) VALUES (?, ?)",
            (999_999, 1),
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised, "expected a foreign key violation for a participant with no game"
