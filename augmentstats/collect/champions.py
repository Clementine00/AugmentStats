"""Fetch/refresh the champion id -> name reference table from Riot's Data Dragon."""

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from augmentstats.db import DEFAULT_DB_PATH, get_connection

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMPION_URL_TEMPLATE = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest_version() -> str:
    return _get_json(VERSIONS_URL)[0]


def fetch_champions(version: str | None = None) -> list[dict]:
    version = version or fetch_latest_version()
    payload = _get_json(CHAMPION_URL_TEMPLATE.format(version=version))
    return list(payload["data"].values())


def store_champions(conn, entries: list[dict], refreshed_at: str) -> dict:
    """Upsert the given champions, then drop entries that vanished upstream.

    Split out from refresh_champions so the pruning logic is testable without
    hitting the network.

    Data Dragon's champion list is not append-only: it has served extra variants
    (Jade_Annie and friends, ids 60001+) at some versions and dropped them at
    later ones. Without pruning, those linger forever and the table only grows.

    Pruning is deliberately conservative. The analysis queries INNER JOIN this
    table, so deleting a champion that games actually reference would make those
    games silently disappear from every report rather than show a blank name.
    Only rows that are both absent from this refresh and unreferenced by any
    participant are removed.
    """
    rows = [
        {
            "champion_id": int(entry["key"]),
            "api_id": entry.get("id"),
            "name": entry.get("name"),
            "title": entry.get("title"),
            "refreshed_at": refreshed_at,
        }
        for entry in entries
    ]

    conn.executemany(
        """
        INSERT INTO champions (champion_id, api_id, name, title, refreshed_at)
        VALUES (:champion_id, :api_id, :name, :title, :refreshed_at)
        ON CONFLICT(champion_id) DO UPDATE SET
            api_id = excluded.api_id,
            name = excluded.name,
            title = excluded.title,
            refreshed_at = excluded.refreshed_at
        """,
        rows,
    )

    # Everything present upstream now carries this refresh's timestamp, so a
    # different (or NULL) one marks a row this refresh did not see. `IS NOT`
    # rather than `<>` so NULL refreshed_at values are matched too.
    pruned = conn.execute(
        """
        DELETE FROM champions
        WHERE refreshed_at IS NOT ?
          AND champion_id NOT IN (SELECT champion_id FROM participants)
        """,
        (refreshed_at,),
    ).rowcount
    conn.commit()

    return {"refreshed": len(rows), "pruned": pruned}


def refresh_champions(db_path: Path = DEFAULT_DB_PATH) -> dict:
    entries = fetch_champions()
    refreshed_at = datetime.now(UTC).isoformat()

    conn = get_connection(db_path)
    try:
        return store_champions(conn, entries, refreshed_at)
    finally:
        conn.close()
