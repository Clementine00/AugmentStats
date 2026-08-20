# AugmentStats

Collect and analyze **League of Legends ARAM Mayhem** games to compute augment
win rates, augment-pair synergies, and per-champion augment performance from your
own match history.

Mayhem reuses the **Arena** augment pool, so augment reference data is sourced
from CommunityDragon's Arena ("cherry") game data, and champion names from Riot's
Data Dragon.

## How it works

The pipeline has three stages:

1. **Export** — `scripts/export-games.ps1` reads your recent match history from the
   running League client (the local LCU API), filters it down to the Mayhem queue,
   and writes each game as raw JSON into `data/raw/`.
2. **Refresh reference data** — `refresh-augments` and `refresh-champions` populate
   lookup tables that map numeric IDs to human-readable augment/champion names.
3. **Ingest** — `ingest` parses the raw JSON files in `data/raw/` and loads games,
   teams, participants, and augment picks into a SQLite database
   (`augmentstats.db`).

Once the data is in the database, the SQL files in `queries/` answer the actual
questions.

```
League client ──(LCU API)──> data/raw/*.json ──(ingest)──> augmentstats.db ──(SQL)──> stats
CommunityDragon / Data Dragon ──(refresh)──────────────────────^
```

## Requirements

- **Python 3.14** (matches the dev container and CI). No third-party **runtime**
  dependencies — the CLI uses only the standard library, and that is deliberate.
  Development tooling (ruff, pytest) is declared in `pyproject.toml`.
- **Windows + PowerShell** to run the exporter (it talks to the local League client).
  The rest of the tooling is cross-platform.
- **`curl.exe`** on `PATH` (bundled with Windows 10/11) for the exporter.
- The **League client must be running** and sitting on the home screen when you export.

A dev container is provided under `.devcontainer/` (Python 3.14 + Node + Claude Code).

## Directory layout

```
augmentstats/            Python package (the CLI lives here)
  cli.py                 argparse entry point: init-db, refresh-*, ingest
  db.py                  SQLite schema, connection, migrations, PROJECT_ROOT
  collect/               everything that WRITES to the database
    ingest.py            parse game.json files -> database rows
    augments.py          refresh augment id -> name/rarity from CommunityDragon
    champions.py         refresh champion id -> name from Data Dragon
data/raw/                downloaded <gameId>.json files (git-ignored)
queries/                 analysis SQL
tests/                   pytest suite (synthetic fixtures only)
scripts/export-games.ps1 exporter that pulls games from the League client
pyproject.toml           dev dependencies + ruff/pytest config
.github/workflows/ci.yml lint and tests on every push and PR
augmentstats.db          SQLite database (git-ignored)
```

## Setup

Create the database schema (also runs migrations on an existing database — it is
safe to run repeatedly):

```
python -m augmentstats init-db
```

Populate the reference tables (do this once, and again after a patch adds new
augments or champions):

```
python -m augmentstats refresh-augments
python -m augmentstats refresh-champions
```

## Importing games

### 1. Export from the League client

Start the League client and get to the home screen, then run:

```powershell
# From the repo root
powershell -File scripts\export-games.ps1 -Count 20
```

This checks your most recent `-Count` games, keeps the ones in the Mayhem queue,
and downloads any not already in `data/raw/`. Games already downloaded are skipped.

> **Export what you can, when you can.** The client only serves a single page of
> recent match history — it ignores paging arguments entirely, so there is no way
> to reach further back than that page. Its size depends on the client's own cache
> (20 and 50 have both been observed). Games that scroll off the end are gone for
> good, so run the exporter regularly rather than saving it up.

Options:

| Parameter        | Default        | Description                                                        |
| ---------------- | -------------- | ------------------------------------------------------------------ |
| `-Count`         | `20`           | How many recent games to check (across all queues, before filtering). Trims the page the client returns — it cannot fetch more; asking for more than it returns warns. |
| `-QueueId`       | `2400`         | Riot queue ID to keep. `2400` = ARAM Mayhem.                       |
| `-OutDir`        | `..\data\raw`  | Where to write `<gameId>.json` files.                              |
| `-LockfilePath`  | auto-detected  | Point at the League `lockfile` directly if auto-detection fails.   |

The exporter auto-detects the client's port and password from the
`LeagueClientUx.exe` lockfile. If the client isn't running it fails with a clear
message.

### 2. Ingest into the database

```
python -m augmentstats ingest
```

By default this reads `data/raw/`. You can pass a different folder, and use
`--force` to re-ingest games already in the database (it deletes and reloads them):

```
python -m augmentstats ingest path\to\folder --force
```

Ingest reports how many games were imported, skipped (already present), or failed.
It handles both UTF-8 and UTF-16 (BOM-prefixed) JSON, since different export
methods encode differently.

## Development

Runtime needs nothing installed. The dev tooling does:

```
python -m venv .venv
.venv\Scripts\python -m pip install --group dev
```

Then the same three commands CI runs:

```
ruff check .
ruff format --check .
pytest
```

Tests use **synthetic** game payloads built in `tests/factories.py` — no real
exported games are committed, since they contain other players' riot IDs and
PUUIDs. `augmentstats.db` and `data/raw/` are git-ignored and stay local.

CI (`.github/workflows/ci.yml`) runs those same three commands on every push to
`main` and every pull request. There is no deploy stage: nothing here is meant to
be published.

Note that a fresh clone has no `data/raw/` directory (git does not store empty
directories), so `ingest` reports `0 imported, 0 skipped, 0 failed` until you
export some games.

## Database schema

SQLite database, default path `augmentstats.db`. Defined in `augmentstats/db.py`.

### `games`

One row per game.

| Column               | Type    | Notes                                                        |
| -------------------- | ------- | ------------------------------------------------------------ |
| `game_id`            | INTEGER | Primary key (Riot game ID).                                  |
| `platform_id`        | TEXT    | e.g. `NA1`.                                                  |
| `game_creation_date` | TEXT    | ISO timestamp from the client.                              |
| `game_duration`      | INTEGER | Seconds.                                                     |
| `game_mode`          | TEXT    |                                                              |
| `game_type`          | TEXT    |                                                              |
| `game_version`       | TEXT    | Full Riot build string, e.g. `16.15.801.3452`.              |
| `patch`              | TEXT    | Derived `major.minor` label, e.g. `16.15` (see Patches).    |
| `map_id`             | INTEGER |                                                              |
| `queue_id`           | INTEGER | `2400` for ARAM Mayhem.                                      |
| `mutators`           | TEXT    | JSON array of `gameModeMutators`.                           |
| `imported_at`        | TEXT    | ISO timestamp when ingested (`NOT NULL`).                   |

### `teams`

One row per team per game. Primary key `(game_id, team_id)`.

| Column            | Type    | Notes                          |
| ----------------- | ------- | ------------------------------ |
| `game_id`         | INTEGER | FK -> `games(game_id)`.        |
| `team_id`         | INTEGER |                                |
| `win`             | TEXT    | `"Win"` / `"Fail"` from Riot.  |
| `tower_kills`     | INTEGER |                                |
| `inhibitor_kills` | INTEGER |                                |
| `dragon_kills`    | INTEGER |                                |
| `baron_kills`     | INTEGER |                                |
| `first_blood`     | INTEGER | 0/1.                           |
| `first_tower`     | INTEGER | 0/1.                           |
| `first_inhibitor` | INTEGER | 0/1.                           |

### `participants`

One row per player per game. Primary key `(game_id, participant_id)`.

| Column                            | Type    | Notes                                            |
| --------------------------------- | ------- | ------------------------------------------------ |
| `game_id`                         | INTEGER | FK -> `games(game_id)`.                          |
| `participant_id`                  | INTEGER | 1–10.                                            |
| `puuid`                           | TEXT    | Backfilled from participant identities.          |
| `summoner_name`                   | TEXT    | In-game name.                                    |
| `champion_id`                     | INTEGER | Join to `champions(champion_id)`.               |
| `team_id`                         | INTEGER |                                                  |
| `win`                             | INTEGER | 0/1 — used for win-rate math.                    |
| `kills` / `deaths` / `assists`    | INTEGER |                                                  |
| `champ_level`                     | INTEGER |                                                  |
| `gold_earned`                     | INTEGER |                                                  |
| `total_damage_dealt_to_champions` | INTEGER |                                                  |
| `total_damage_taken`              | INTEGER |                                                  |
| `total_heal`                      | INTEGER |                                                  |
| `vision_score`                    | INTEGER |                                                  |
| `wards_placed` / `wards_killed`   | INTEGER |                                                  |
| `cs`                              | INTEGER | minions + neutral monsters.                     |
| `lane` / `role`                   | TEXT    | From the timeline.                              |
| `item0`–`item6`                   | INTEGER | Item IDs in each slot.                          |
| `stats_json`                      | TEXT    | Full raw `stats` blob for anything not columned. |

### `participant_augments`

One row per augment chosen by a player. Primary key `(game_id, participant_id, slot)`.

| Column           | Type    | Notes                                             |
| ---------------- | ------- | ------------------------------------------------- |
| `game_id`        | INTEGER | Part of FK -> `participants`.                     |
| `participant_id` | INTEGER | Part of FK -> `participants`.                     |
| `slot`           | INTEGER | Augment slot 1–6.                                 |
| `augment_id`     | INTEGER | Join to `augments(augment_id)`.                   |

### `augments` (reference)

Full Arena augment pool from CommunityDragon; a superset of what appears in Mayhem.

| Column         | Type    | Notes                                          |
| -------------- | ------- | ---------------------------------------------- |
| `augment_id`   | INTEGER | Primary key.                                   |
| `api_name`     | TEXT    | Internal name ID.                              |
| `name`         | TEXT    | Display name.                                  |
| `rarity`       | TEXT    | `kSilver` / `kGold` / `kPrismatic`.            |
| `icon_path`    | TEXT    |                                                |
| `refreshed_at` | TEXT    | ISO timestamp of last refresh.                 |

### `champions` (reference)

Champion ID -> name mapping from Data Dragon.

| Column         | Type    | Notes                          |
| -------------- | ------- | ------------------------------ |
| `champion_id`  | INTEGER | Primary key (Riot numeric key).|
| `api_id`       | TEXT    | e.g. `MonkeyKing`.             |
| `name`         | TEXT    | Display name, e.g. `Wukong`.   |
| `title`        | TEXT    |                                |
| `refreshed_at` | TEXT    | ISO timestamp of last refresh. |

### Indexes

- `idx_participants_game` on `participants(game_id)`
- `idx_participant_augments_augment` on `participant_augments(augment_id)`
- `idx_games_patch` on `games(patch)`

## Patches

Each game stores a derived `patch` label (`major.minor`, e.g. `16.15`) alongside
Riot's full `game_version`. Hotfix builds within a patch (e.g. `16.15.801` and
`16.15.802`) collapse to the same label so games group correctly for balance
comparisons.

This is populated automatically at ingest, and `init-db` backfills the column for
any games ingested before it existed. To slice any analysis by patch, filter on
`games.patch`:

```sql
... JOIN games g ON g.game_id = pa.game_id
WHERE g.patch = '16.15'
```

## Querying

The database is plain SQLite — query it with any client:

```
sqlite3 augmentstats.db < queries/augment_winrates.sql
```

Provided queries in `queries/`:

| File                              | What it answers                                                        |
| --------------------------------- | --------------------------------------------------------------------- |
| `augment_winrates.sql`            | Win rate and pick count per augment.                                  |
| `augment_winrates_by_patch.sql`   | The same, broken down by patch to track an augment across balance changes. |
| `augment_combos.sql`              | Win rate for augment pairs (order-independent), with a minimum sample size. |
| `champion_augment_winrates.sql`   | Win rate per (champion, augment) pair.                                |

Each single-patch query has a commented `-- WHERE g.patch = '...'` line you can
uncomment to restrict results to one patch.

> **Sample size matters.** With a small number of games, 100% / 0% win rates are
> usually one or two picks, not signal. Raise the `HAVING`/pick thresholds in the
> queries as your dataset grows.

## Typical workflow

The **server owns the database**. Windows exports games and ships them; the
server ingests and answers questions. See [Server](#server) for the details.

```
# Each session, on Windows with the League client open
powershell -File scripts\export-games.ps1 -Count 20
powershell -File scripts\sync-to-server.ps1

# Analyze, on the server
ssh <server> "cd /srv/augmentstats && sqlite3 augmentstats.db < queries/augment_winrates.sql"

# After a game patch adds augments, on the server
ssh <server> "cd /srv/augmentstats && python3 -m augmentstats refresh-augments"
```

Running everything locally still works (`init-db`, `ingest`, then query
`augmentstats.db` directly) -- it is just no longer the source of truth.

## Server

The database lives on a Linux host at `/srv/augmentstats`, a clone of this
repository plus two git-ignored artifacts: `data/raw/` and `augmentstats.db`.

Why the split: `export-games.ps1` needs a running Windows League client, so games
can only originate on Windows. Everything after that runs on the server. **Raw
JSON is the transport, not the database** -- the server's database is therefore
always rebuildable from the files it already holds, and there is exactly one
writer.

```
Windows                              Server
-------                              ------
export-games.ps1
  -> data/raw/*.json
  --- sync-to-server.ps1 (scp) --->  data/raw/*.json
                                     ingest
                                       -> augmentstats.db   (source of truth)
```

### One-time setup

```bash
sudo mkdir -p /srv/augmentstats && sudo chown "$USER:$USER" /srv/augmentstats
git clone https://github.com/Clementine00/AugmentStats.git /srv/augmentstats
cd /srv/augmentstats
sudo apt install sqlite3          # Python's sqlite3 module is built in; this is the CLI
mkdir -p data/raw                 # git does not store empty directories
python3 -m augmentstats init-db
python3 -m augmentstats refresh-augments
python3 -m augmentstats refresh-champions
```

Needs Python 3.14 (matching local and CI) and SSH key auth from the Windows box.

### Syncing

```powershell
powershell -File scripts\sync-to-server.ps1
```

Runs `git pull` on the server, asks which games it already has, copies only the
missing ones, runs ingest remotely and prints the result. `scp` is used rather
than `rsync` because rsync would have to exist on both ends and Windows has none.

The pull matters because **nothing else deploys code to the server** -- merging a
pull request does not touch it, so without this it would keep running whatever
commit was last pulled. The data directories are git-ignored, so a pull can never
disturb the database or the exported games. A failed pull warns loudly and
continues with the code already there, rather than blocking games from being
collected; pass `-SkipPull` to skip it entirely.

The SSH target is resolved in this order: `-Server user@host`, then the
`AUGMENTSTATS_SERVER` environment variable, then a `server.local` file in the repo
root. `server.local` is git-ignored so the address stays out of this public
repository.

## Notes and caveats

- The exporter is Windows-only because it reads the local League client's lockfile
  and calls the LCU API.
- `refresh-augments` pulls from CommunityDragon's `/latest/` path, which can be
  **ahead of your live client** (it may include augments from a not-yet-live
  patch). Extra reference entries are harmless — they only appear in results if an
  actual game contains them. Pin the URL in `augmentstats/collect/augments.py` to a specific
  version if you need the reference table to match live exactly.
- `data/raw/*.json` and `augmentstats.db` are git-ignored; the database is rebuildable
  from the raw files via `ingest`.
