"""Refreshing the champion reference table.

store_champions is tested directly so the pruning logic is covered without
touching the network.
"""

from augmentstats.collect.champions import store_champions
from augmentstats.collect.ingest import ingest_game
from tests.factories import make_game, make_participant

T1 = "2026-08-06T00:00:00+00:00"
T2 = "2026-08-13T00:00:00+00:00"


def _entry(champion_id: int, name: str) -> dict:
    """Data Dragon's shape: numeric id arrives as a string under 'key'."""
    return {"key": str(champion_id), "id": name, "name": name, "title": f"the {name}"}


def _ids(conn) -> set[int]:
    return {r[0] for r in conn.execute("SELECT champion_id FROM champions")}


def test_inserts_and_reports_counts(conn):
    result = store_champions(conn, [_entry(103, "Ahri"), _entry(101, "Xerath")], T1)

    assert result == {"refreshed": 2, "pruned": 0}
    assert _ids(conn) == {103, 101}


def test_existing_entries_are_updated_not_duplicated(conn):
    store_champions(conn, [_entry(103, "Ahri")], T1)
    store_champions(conn, [_entry(103, "Ahri Renamed")], T2)

    rows = conn.execute("SELECT champion_id, name FROM champions").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Ahri Renamed"


def test_entries_that_vanish_upstream_are_pruned(conn):
    """Data Dragon has served Jade_* variants (ids 60001+) and later dropped them."""
    store_champions(conn, [_entry(103, "Ahri"), _entry(60001, "Jade_Annie")], T1)
    assert _ids(conn) == {103, 60001}

    result = store_champions(conn, [_entry(103, "Ahri")], T2)

    assert result == {"refreshed": 1, "pruned": 1}
    assert _ids(conn) == {103}, "the vanished variant should be gone"


def test_referenced_champions_are_never_pruned(conn):
    """The safety property.

    The analysis queries INNER JOIN champions, so dropping a champion that games
    reference would make those games vanish from every report instead of showing
    a blank name. A played champion must survive even if it disappears upstream.
    """
    store_champions(conn, [_entry(103, "Ahri"), _entry(60001, "Jade_Annie")], T1)
    game = make_game(participants=[make_participant(1, champion_id=60001)])
    ingest_game(conn, game, "2026-08-20T00:00:00+00:00")
    conn.commit()

    result = store_champions(conn, [_entry(103, "Ahri")], T2)

    assert 60001 in _ids(conn), "a champion with games must not be pruned"
    assert result["pruned"] == 0

    played = conn.execute(
        "SELECT ch.name FROM participants p JOIN champions ch ON ch.champion_id = p.champion_id"
    ).fetchall()
    assert len(played) == 1, "the game must still resolve through the join"


def test_rows_with_null_refreshed_at_are_pruned(conn):
    """Guards the `IS NOT` in the delete -- `<> ?` would never match NULL."""
    conn.execute("INSERT INTO champions (champion_id, name) VALUES (?, ?)", (999, "Legacy"))
    conn.commit()

    result = store_champions(conn, [_entry(103, "Ahri")], T2)

    assert result["pruned"] == 1
    assert _ids(conn) == {103}
