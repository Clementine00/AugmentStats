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


def refresh_champions(db_path: Path = DEFAULT_DB_PATH) -> int:
    entries = fetch_champions()
    refreshed_at = datetime.now(UTC).isoformat()

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

    conn = get_connection(db_path)
    try:
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
        conn.commit()
        return len(rows)
    finally:
        conn.close()
