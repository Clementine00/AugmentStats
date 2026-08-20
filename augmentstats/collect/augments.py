"""Fetch/refresh the augment id -> name/rarity reference table from CommunityDragon.

ARAM Mayhem reuses the Arena augment pool, whose data CommunityDragon publishes
under the "cherry" (Arena's internal codename) game-data path.
"""

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from augmentstats.db import DEFAULT_DB_PATH, get_connection

AUGMENTS_URL = (
    "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
    "global/default/v1/cherry-augments.json"
)


def fetch_augments(url: str = AUGMENTS_URL) -> list[dict]:
    # CommunityDragon rejects the default urllib User-Agent; send a browser-like one.
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def refresh_augments(db_path: Path = DEFAULT_DB_PATH, url: str = AUGMENTS_URL) -> int:
    entries = fetch_augments(url)
    refreshed_at = datetime.now(UTC).isoformat()

    conn = get_connection(db_path)
    try:
        rows = [
            {
                "id": entry["id"],
                "augmentNameId": entry.get("augmentNameId"),
                "nameTRA": entry.get("nameTRA"),
                "rarity": entry.get("rarity"),
                "augmentSmallIconPath": entry.get("augmentSmallIconPath"),
                "refreshed_at": refreshed_at,
            }
            for entry in entries
        ]
        conn.executemany(
            """
            INSERT INTO augments (augment_id, api_name, name, rarity, icon_path, refreshed_at)
            VALUES (:id, :augmentNameId, :nameTRA, :rarity, :augmentSmallIconPath, :refreshed_at)
            ON CONFLICT(augment_id) DO UPDATE SET
                api_name = excluded.api_name,
                name = excluded.name,
                rarity = excluded.rarity,
                icon_path = excluded.icon_path,
                refreshed_at = excluded.refreshed_at
            """,
            rows,
        )
        conn.commit()
        return len(entries)
    finally:
        conn.close()
