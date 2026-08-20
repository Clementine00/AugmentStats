"""SQLite schema and connection helper for AugmentStats."""

import sqlite3
from pathlib import Path

# Single anchor for every on-disk path in the project. Modules deeper in the
# package (collect/, stats/, web/) import this instead of walking up from their
# own __file__, so moving a module can never silently repoint a default path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH = PROJECT_ROOT / "augmentstats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY,
    platform_id TEXT,
    game_creation_date TEXT,
    game_duration INTEGER,
    game_mode TEXT,
    game_type TEXT,
    game_version TEXT,
    patch TEXT,
    map_id INTEGER,
    queue_id INTEGER,
    mutators TEXT,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    team_id INTEGER NOT NULL,
    win TEXT,
    tower_kills INTEGER,
    inhibitor_kills INTEGER,
    dragon_kills INTEGER,
    baron_kills INTEGER,
    first_blood INTEGER,
    first_tower INTEGER,
    first_inhibitor INTEGER,
    PRIMARY KEY (game_id, team_id)
);

CREATE TABLE IF NOT EXISTS participants (
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    participant_id INTEGER NOT NULL,
    puuid TEXT,
    summoner_name TEXT,
    champion_id INTEGER,
    team_id INTEGER,
    win INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    champ_level INTEGER,
    gold_earned INTEGER,
    total_damage_dealt_to_champions INTEGER,
    total_damage_taken INTEGER,
    total_heal INTEGER,
    vision_score INTEGER,
    wards_placed INTEGER,
    wards_killed INTEGER,
    cs INTEGER,
    lane TEXT,
    role TEXT,
    item0 INTEGER,
    item1 INTEGER,
    item2 INTEGER,
    item3 INTEGER,
    item4 INTEGER,
    item5 INTEGER,
    item6 INTEGER,
    stats_json TEXT,
    PRIMARY KEY (game_id, participant_id)
);

CREATE TABLE IF NOT EXISTS participant_augments (
    game_id INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    augment_id INTEGER NOT NULL,
    PRIMARY KEY (game_id, participant_id, slot),
    FOREIGN KEY (game_id, participant_id) REFERENCES participants(game_id, participant_id)
);

CREATE TABLE IF NOT EXISTS augments (
    augment_id INTEGER PRIMARY KEY,
    api_name TEXT,
    name TEXT,
    rarity TEXT,
    icon_path TEXT,
    refreshed_at TEXT
);

CREATE TABLE IF NOT EXISTS champions (
    champion_id INTEGER PRIMARY KEY,
    api_id TEXT,
    name TEXT,
    title TEXT,
    refreshed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_participants_game ON participants(game_id);
CREATE INDEX IF NOT EXISTS idx_participant_augments_augment ON participant_augments(augment_id);
"""


def patch_from_version(game_version: str | None) -> str | None:
    """Derive the 'major.minor' patch label (e.g. '16.15') from Riot's
    gameVersion string (e.g. '16.15.801.3452').

    The trailing build/hotfix segments are dropped so games on the same patch
    group together. Returns None if the version is missing or unparseable.
    """
    if not game_version:
        return None
    parts = game_version.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"
    return None


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


ITEM_COLUMNS = ["item0", "item1", "item2", "item3", "item4", "item5", "item6"]


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database's initial creation."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(participants)")}
    for column in ITEM_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE participants ADD COLUMN {column} INTEGER")

    game_columns = {row["name"] for row in conn.execute("PRAGMA table_info(games)")}
    if "patch" not in game_columns:
        conn.execute("ALTER TABLE games ADD COLUMN patch TEXT")
        # Backfill patch for games ingested before the column existed.
        for row in conn.execute("SELECT game_id, game_version FROM games").fetchall():
            conn.execute(
                "UPDATE games SET patch = ? WHERE game_id = ?",
                (patch_from_version(row["game_version"]), row["game_id"]),
            )

    # Created here (not in SCHEMA) so it runs after the patch column is guaranteed
    # to exist on databases created before that column was added.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_games_patch ON games(patch)")


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
