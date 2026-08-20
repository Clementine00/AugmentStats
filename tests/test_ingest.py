"""Parsing exported game JSON into database rows."""

import json

from augmentstats.collect.ingest import (
    delete_game,
    game_exists,
    ingest_folder,
    ingest_game,
    read_json_file,
)
from augmentstats.db import get_connection
from tests.factories import make_game, make_participant, write_game

IMPORTED_AT = "2026-08-20T12:00:00+00:00"


def _ingest(conn, game):
    ingest_game(conn, game, IMPORTED_AT)
    conn.commit()


def test_game_row_records_derived_patch_and_mutators(conn):
    _ingest(conn, make_game(game_id=42, game_version="16.16.900.1111"))

    row = conn.execute("SELECT * FROM games WHERE game_id = 42").fetchone()
    assert row["patch"] == "16.16", "patch is derived, not taken from the payload"
    assert row["game_version"] == "16.16.900.1111"
    assert row["queue_id"] == 2400
    assert json.loads(row["mutators"]) == ["MAYHEM"]
    assert row["imported_at"] == IMPORTED_AT


def test_teams_and_participants_are_loaded(conn):
    _ingest(conn, make_game())

    assert conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == 10


def test_win_is_stored_as_integer_not_boolean(conn):
    """Every win-rate query does SUM(p.win), so this must be 0/1, never text."""
    _ingest(conn, make_game())

    values = {r[0] for r in conn.execute("SELECT DISTINCT win FROM participants")}
    assert values == {0, 1}

    winners = conn.execute("SELECT COUNT(*) FROM participants WHERE win = 1").fetchone()[0]
    assert winners == 5


def test_cs_sums_minions_and_neutral_monsters(conn):
    game = make_game(participants=[make_participant(1, minions=100, neutral=23)])
    _ingest(conn, game)

    assert conn.execute("SELECT cs FROM participants").fetchone()[0] == 123


def test_cs_handles_missing_minion_counts(conn):
    """Riot omits these fields in some payloads; ingest coerces None to 0."""
    participant = make_participant(1)
    del participant["stats"]["totalMinionsKilled"]
    participant["stats"]["neutralMinionsKilled"] = None
    _ingest(conn, make_game(participants=[participant]))

    assert conn.execute("SELECT cs FROM participants").fetchone()[0] == 0


def test_summoner_name_and_puuid_come_from_identities(conn):
    _ingest(conn, make_game())

    row = conn.execute(
        "SELECT summoner_name, puuid FROM participants WHERE participant_id = 3"
    ).fetchone()
    assert row["summoner_name"] == "Player3"
    assert row["puuid"] == "00000000-0000-0000-0000-000000000003", "puuid is backfilled"


def test_augment_slots_are_one_based(conn):
    game = make_game(participants=[make_participant(1, augments=(11, 22, 33, 44))])
    _ingest(conn, game)

    rows = dict(conn.execute("SELECT slot, augment_id FROM participant_augments"))
    assert rows == {1: 11, 2: 22, 3: 33, 4: 44}


def test_zero_augment_ids_are_skipped_leaving_gaps(conn):
    """A 0 means an empty slot. Real games do have sparse slots."""
    game = make_game(participants=[make_participant(1, augments=(11, 0, 33, 0))])
    _ingest(conn, game)

    rows = dict(conn.execute("SELECT slot, augment_id FROM participant_augments"))
    assert rows == {1: 11, 3: 33}


def test_supports_up_to_six_augment_slots(conn):
    game = make_game(participants=[make_participant(1, augments=(1, 2, 3, 4, 5, 6))])
    _ingest(conn, game)

    slots = [r[0] for r in conn.execute("SELECT slot FROM participant_augments ORDER BY slot")]
    assert slots == [1, 2, 3, 4, 5, 6]


def test_delete_game_removes_all_child_rows(conn):
    _ingest(conn, make_game(game_id=7))
    assert game_exists(conn, 7)

    delete_game(conn, 7)
    conn.commit()

    assert not game_exists(conn, 7)
    for table in ("teams", "participants", "participant_augments"):
        remaining = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE game_id = 7").fetchone()[0]
        assert remaining == 0, f"{table} still has rows for the deleted game"


def test_read_json_file_handles_utf16_with_bom(tmp_path):
    """The exporter has produced both encodings; read_json_file sniffs the BOM."""
    folder = tmp_path / "raw"
    write_game(folder, make_game(game_id=1), encoding="utf-16")

    data = read_json_file(folder / "1.json")
    assert data["gameId"] == 1


def test_ingest_folder_imports_then_skips(raw_dir, db_path):
    write_game(raw_dir, make_game(game_id=1))
    write_game(raw_dir, make_game(game_id=2))

    first = ingest_folder(raw_dir, db_path)
    assert len(first["imported"]) == 2
    assert first["skipped"] == [] and first["failed"] == []

    second = ingest_folder(raw_dir, db_path)
    assert second["imported"] == [], "already-present games must not be re-imported"
    assert len(second["skipped"]) == 2


def test_force_reingests_without_duplicating_rows(raw_dir, db_path):
    write_game(raw_dir, make_game(game_id=1))
    ingest_folder(raw_dir, db_path)

    result = ingest_folder(raw_dir, db_path, force=True)
    assert len(result["imported"]) == 1

    conn = get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == 10
    conn.close()


def test_both_encodings_ingest_from_the_same_folder(raw_dir, db_path):
    write_game(raw_dir, make_game(game_id=1), encoding="utf-8")
    write_game(raw_dir, make_game(game_id=2), encoding="utf-16")

    result = ingest_folder(raw_dir, db_path)
    assert len(result["imported"]) == 2, result["failed"]


def test_malformed_file_is_reported_not_raised(raw_dir, db_path):
    """One bad file must not abort the whole run."""
    write_game(raw_dir, make_game(game_id=1))
    (raw_dir / "broken.json").write_text("{ this is not json", encoding="utf-8")

    result = ingest_folder(raw_dir, db_path)
    assert len(result["imported"]) == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0][0] == "broken.json"


def test_missing_folder_is_handled(tmp_path, db_path):
    """A fresh clone has no data/raw; ingest should report nothing, not crash."""
    result = ingest_folder(tmp_path / "does-not-exist", db_path)
    assert result == {"imported": [], "skipped": [], "failed": []}
