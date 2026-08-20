"""Parse exported game.json files and load them into the AugmentStats database."""

import json
from datetime import UTC, datetime
from pathlib import Path

from augmentstats.db import (
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    get_connection,
    patch_from_version,
)

DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# BOM byte sequences used to detect text encoding of exported files.
# `curl.exe ... > file` on PowerShell writes UTF-16LE with a BOM; other
# export methods (e.g. curl -o on cmd.exe, or the raw API response) are UTF-8.
_BOM_ENCODINGS = {
    b"\xff\xfe": "utf-16",
    b"\xfe\xff": "utf-16",
    b"\xef\xbb\xbf": "utf-8-sig",
}


def read_json_file(path: Path) -> dict:
    raw = path.read_bytes()
    encoding = "utf-8"
    for bom, enc in _BOM_ENCODINGS.items():
        if raw.startswith(bom):
            encoding = enc
            break
    return json.loads(raw.decode(encoding))


def _augment_slots(stats: dict):
    for slot in range(1, 7):
        augment_id = stats.get(f"playerAugment{slot}", 0)
        if augment_id:
            yield slot, augment_id


def ingest_game(conn, data: dict, imported_at: str) -> None:
    game_id = data["gameId"]

    conn.execute(
        """
        INSERT INTO games (
            game_id, platform_id, game_creation_date, game_duration,
            game_mode, game_type, game_version, patch, map_id, queue_id, mutators, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            data.get("platformId"),
            data.get("gameCreationDate"),
            data.get("gameDuration"),
            data.get("gameMode"),
            data.get("gameType"),
            data.get("gameVersion"),
            patch_from_version(data.get("gameVersion")),
            data.get("mapId"),
            data.get("queueId"),
            json.dumps(data.get("gameModeMutators", [])),
            imported_at,
        ),
    )

    for team in data.get("teams", []):
        conn.execute(
            """
            INSERT INTO teams (
                game_id, team_id, win, tower_kills, inhibitor_kills,
                dragon_kills, baron_kills, first_blood, first_tower, first_inhibitor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                team.get("teamId"),
                team.get("win"),
                team.get("towerKills"),
                team.get("inhibitorKills"),
                team.get("dragonKills"),
                team.get("baronKills"),
                int(team.get("firstBlood", False)),
                int(team.get("firstTower", False)),
                int(team.get("firstInhibitor", False)),
            ),
        )

    names_by_participant_id = {
        identity["participantId"]: identity["player"].get("gameName", "")
        for identity in data.get("participantIdentities", [])
    }

    for participant in data.get("participants", []):
        participant_id = participant["participantId"]
        stats = participant.get("stats", {})
        timeline = participant.get("timeline", {})

        conn.execute(
            """
            INSERT INTO participants (
                game_id, participant_id, puuid, summoner_name, champion_id, team_id, win,
                kills, deaths, assists, champ_level, gold_earned,
                total_damage_dealt_to_champions, total_damage_taken, total_heal,
                vision_score, wards_placed, wards_killed, cs, lane, role,
                item0, item1, item2, item3, item4, item5, item6, stats_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                game_id,
                participant_id,
                None,
                names_by_participant_id.get(participant_id, ""),
                participant.get("championId"),
                participant.get("teamId"),
                int(stats.get("win", False)),
                stats.get("kills"),
                stats.get("deaths"),
                stats.get("assists"),
                stats.get("champLevel"),
                stats.get("goldEarned"),
                stats.get("totalDamageDealtToChampions"),
                stats.get("totalDamageTaken"),
                stats.get("totalHeal"),
                stats.get("visionScore"),
                stats.get("wardsPlaced"),
                stats.get("wardsKilled"),
                (stats.get("totalMinionsKilled") or 0) + (stats.get("neutralMinionsKilled") or 0),
                timeline.get("lane"),
                timeline.get("role"),
                stats.get("item0"),
                stats.get("item1"),
                stats.get("item2"),
                stats.get("item3"),
                stats.get("item4"),
                stats.get("item5"),
                stats.get("item6"),
                json.dumps(stats),
            ),
        )

        for slot, augment_id in _augment_slots(stats):
            conn.execute(
                """
                INSERT INTO participant_augments (game_id, participant_id, slot, augment_id)
                VALUES (?, ?, ?, ?)
                """,
                (game_id, participant_id, slot, augment_id),
            )

    # puuid lives on participantIdentities, not participants; backfill it.
    for identity in data.get("participantIdentities", []):
        conn.execute(
            "UPDATE participants SET puuid = ? WHERE game_id = ? AND participant_id = ?",
            (identity["player"].get("puuid"), game_id, identity["participantId"]),
        )


def game_exists(conn, game_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM games WHERE game_id = ?", (game_id,)).fetchone()
    return row is not None


def delete_game(conn, game_id: int) -> None:
    conn.execute("DELETE FROM participant_augments WHERE game_id = ?", (game_id,))
    conn.execute("DELETE FROM participants WHERE game_id = ?", (game_id,))
    conn.execute("DELETE FROM teams WHERE game_id = ?", (game_id,))
    conn.execute("DELETE FROM games WHERE game_id = ?", (game_id,))


def ingest_folder(
    folder: Path = DEFAULT_RAW_DIR, db_path: Path = DEFAULT_DB_PATH, force: bool = False
) -> dict:
    summary = {"imported": [], "skipped": [], "failed": []}
    files = sorted(folder.glob("*.json"))

    conn = get_connection(db_path)
    try:
        for path in files:
            try:
                data = read_json_file(path)
                game_id = data["gameId"]
            except Exception as exc:  # noqa: BLE001 - report and continue
                summary["failed"].append((path.name, str(exc)))
                continue

            already_present = game_exists(conn, game_id)
            if already_present and not force:
                summary["skipped"].append((path.name, game_id))
                continue

            try:
                if already_present:
                    delete_game(conn, game_id)
                ingest_game(conn, data, datetime.now(UTC).isoformat())
                conn.commit()
                summary["imported"].append((path.name, game_id))
            except Exception as exc:  # noqa: BLE001 - report and continue
                conn.rollback()
                summary["failed"].append((path.name, str(exc)))
    finally:
        conn.close()

    return summary
