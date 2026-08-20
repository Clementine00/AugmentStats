"""CLI for AugmentStats: python -m augmentstats <command>"""

import argparse
from pathlib import Path

from augmentstats.augments import refresh_augments
from augmentstats.champions import refresh_champions
from augmentstats.db import DEFAULT_DB_PATH, init_db
from augmentstats.ingest import DEFAULT_RAW_DIR, ingest_folder


def cmd_init_db(args: argparse.Namespace) -> None:
    init_db(args.db)
    print(f"Initialized database at {args.db}")


def cmd_refresh_augments(args: argparse.Namespace) -> None:
    count = refresh_augments(args.db)
    print(f"Refreshed {count} augments in {args.db}")


def cmd_refresh_champions(args: argparse.Namespace) -> None:
    count = refresh_champions(args.db)
    print(f"Refreshed {count} champions in {args.db}")


def cmd_ingest(args: argparse.Namespace) -> None:
    summary = ingest_folder(args.folder, args.db, force=args.force)
    for name, game_id in summary["imported"]:
        print(f"imported  {name} (game_id={game_id})")
    for name, game_id in summary["skipped"]:
        print(f"skipped   {name} (game_id={game_id}, already in db)")
    for name, error in summary["failed"]:
        print(f"failed    {name}: {error}")
    print(
        f"\n{len(summary['imported'])} imported, "
        f"{len(summary['skipped'])} skipped, "
        f"{len(summary['failed'])} failed"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="augmentstats")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="Path to the SQLite database file"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create the database schema").set_defaults(
        func=cmd_init_db
    )
    subparsers.add_parser(
        "refresh-augments", help="Fetch augment id -> name/rarity data from CommunityDragon"
    ).set_defaults(func=cmd_refresh_augments)
    subparsers.add_parser(
        "refresh-champions", help="Fetch champion id -> name data from Data Dragon"
    ).set_defaults(func=cmd_refresh_champions)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest exported game.json files")
    ingest_parser.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=DEFAULT_RAW_DIR,
        help="Folder of game.json files to ingest (default: data/raw)",
    )
    ingest_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest games already in the database (deletes and reloads them) instead of skipping",
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
