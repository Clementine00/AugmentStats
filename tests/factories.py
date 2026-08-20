"""Builders for synthetic game payloads.

No real game JSON is committed to this repo -- exported games contain other
players' riot IDs and PUUIDs -- so tests construct the shapes they need.
"""

import json

# A realistic gameVersion; patch_from_version() should reduce this to "16.15".
GAME_VERSION = "16.15.801.3452"


def make_participant(
    participant_id: int,
    *,
    champion_id: int = 100,
    team_id: int = 100,
    win: bool = True,
    augments: tuple[int, ...] = (101, 102, 103, 104),
    minions: int = 30,
    neutral: int = 12,
) -> dict:
    """One participant in Riot's shape.

    `augments` is positional: index 0 becomes playerAugment1, and so on. A 0
    means "no augment in that slot" -- ingest skips those, which is how real
    games with fewer than four augments come through.
    """
    stats = {
        "win": win,
        "kills": 5,
        "deaths": 3,
        "assists": 7,
        "champLevel": 18,
        "goldEarned": 12000,
        "totalDamageDealtToChampions": 25000,
        "totalDamageTaken": 30000,
        "totalHeal": 4000,
        "visionScore": 8,
        "wardsPlaced": 2,
        "wardsKilled": 1,
        "totalMinionsKilled": minions,
        "neutralMinionsKilled": neutral,
        "item0": 3153,
        "item1": 3006,
        "item2": 0,
        "item3": 0,
        "item4": 0,
        "item5": 0,
        "item6": 3340,
    }
    for index, augment_id in enumerate(augments, start=1):
        stats[f"playerAugment{index}"] = augment_id

    return {
        "participantId": participant_id,
        "championId": champion_id,
        "teamId": team_id,
        "stats": stats,
        "timeline": {"lane": "MIDDLE", "role": "SOLO"},
    }


def make_game(
    game_id: int = 5_000_000_001,
    *,
    game_version: str = GAME_VERSION,
    queue_id: int = 2400,
    participants: list[dict] | None = None,
) -> dict:
    """A whole game in the shape ingest expects, with matching identities."""
    if participants is None:
        participants = [
            make_participant(i, champion_id=100 + i, team_id=100 if i <= 5 else 200, win=i <= 5)
            for i in range(1, 11)
        ]

    identities = [
        {
            "participantId": p["participantId"],
            "player": {
                "gameName": f"Player{p['participantId']}",
                "puuid": f"00000000-0000-0000-0000-{p['participantId']:012d}",
            },
        }
        for p in participants
    ]

    return {
        "gameId": game_id,
        "platformId": "NA1",
        "gameCreationDate": "2026-08-20T07:07:16.733Z",
        "gameDuration": 1100,
        "gameMode": "ARAM",
        "gameType": "MATCHED_GAME",
        "gameVersion": game_version,
        "mapId": 12,
        "queueId": queue_id,
        "gameModeMutators": ["MAYHEM"],
        "teams": [
            {
                "teamId": 100,
                "win": "Win",
                "towerKills": 5,
                "inhibitorKills": 1,
                "dragonKills": 2,
                "baronKills": 0,
                "firstBlood": True,
                "firstTower": True,
                "firstInhibitor": False,
            },
            {
                "teamId": 200,
                "win": "Fail",
                "towerKills": 2,
                "inhibitorKills": 0,
                "dragonKills": 1,
                "baronKills": 0,
                "firstBlood": False,
                "firstTower": False,
                "firstInhibitor": False,
            },
        ],
        "participants": participants,
        "participantIdentities": identities,
    }


def write_game(folder, game: dict, *, encoding: str = "utf-8") -> None:
    """Write a game to <folder>/<gameId>.json in the given encoding.

    The exporter has produced both UTF-8 and UTF-16-with-BOM over time, so
    read_json_file sniffs the BOM. That is a property of the file, not of Riot's
    data, which is why synthetic fixtures can exercise it faithfully.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{game['gameId']}.json"
    path.write_bytes(json.dumps(game).encode(encoding))
