"""Shared SQLite storage for the application and the SSH worker publisher."""

import argparse
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


STATUSES = ("Ciekawe", "Do sprawdzenia", "Obejrzane", "Odrzucone", "Nieaktualne")
FIELDS = (
    "id", "url", "found", "listing_date", "fresh", "status", "activity", "location",
    "portal", "rent", "fees", "total", "area", "rooms", "pets", "extras",
    "description", "fee_details", "notes", "verified_at", "title",
)
SCHEMA = """
CREATE TABLE listings (
    id TEXT PRIMARY KEY NOT NULL, url TEXT NOT NULL UNIQUE,
    found TEXT, listing_date TEXT, fresh TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Ciekawe','Do sprawdzenia','Obejrzane','Odrzucone','Nieaktualne')),
    activity TEXT NOT NULL, location TEXT NOT NULL, portal TEXT NOT NULL,
    rent REAL, fees REAL, total REAL, area REAL, rooms INTEGER,
    pets TEXT NOT NULL, extras TEXT NOT NULL, description TEXT NOT NULL,
    fee_details TEXT NOT NULL, notes TEXT NOT NULL, verified_at TEXT, title TEXT NOT NULL
);
CREATE TABLE galleries (
    url TEXT NOT NULL REFERENCES listings(url), position INTEGER NOT NULL,
    path TEXT NOT NULL, PRIMARY KEY(url, position)
);
CREATE TABLE sources (
    name TEXT PRIMARY KEY NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok','partial','error')),
    new INTEGER NOT NULL, errors TEXT NOT NULL CHECK(json_valid(errors)), checked_at TEXT NOT NULL
);
CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id = 1), last_run TEXT);
INSERT INTO metadata VALUES (1, NULL);
PRAGMA user_version = 1;
"""


@contextmanager
def connect(path, mode="rw"):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=" + mode, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unsupported Chata database schema")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path):
    path = Path(path)
    with path.open("xb"):
        pass
    connection = sqlite3.connect(path)
    try:
        connection.executescript("BEGIN;" + SCHEMA + "COMMIT;")
    finally:
        connection.close()


def new_listing(listing):
    return {
        "id": listing["id"], "url": listing["url"], "found": listing["found"],
        "listing_date": None, "fresh": "TAK", "status": "Do sprawdzenia", "activity": "Aktywne",
        "location": listing["location"], "portal": listing["portal"], "rent": listing["rent"],
        "rooms": listing["rooms"], **listing["parameters"],
        "extras": "", "description": listing["description"], "notes": "",
        "verified_at": None, "title": listing["title"],
    }


def read(path):
    with connect(path, "ro") as connection:
        connection.execute("BEGIN")
        listings = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM listings ORDER BY rowid")}
        galleries = {}
        for row in connection.execute("SELECT * FROM galleries ORDER BY url, position"):
            if row["url"] not in galleries:
                galleries[row["url"]] = []
            galleries[row["url"]].append(row["path"])
        sources = {}
        for row in connection.execute("SELECT * FROM sources ORDER BY name"):
            source = dict(row)
            del source["name"]
            source["errors"] = json.loads(source["errors"])
            sources[row["name"]] = source
        last_run = connection.execute("SELECT last_run FROM metadata WHERE id = 1").fetchone()[0]
    return {"listings": listings, "galleries": galleries, "sources": sources, "last_run": last_run}


def merge(path, snapshot):
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = ",".join(FIELDS)
        placeholders = ",".join("?" for _ in FIELDS)
        refreshed = ("title", "description", "location", "rent", "rooms", "area", "fees", "total", "pets", "fee_details", "verified_at")
        updates = ",".join(f"{field}=excluded.{field}" for field in refreshed)
        for listing in snapshot["listings"].values():
            connection.execute(
                f"INSERT INTO listings ({columns}) VALUES ({placeholders}) ON CONFLICT(url) DO UPDATE SET {updates} "
                "WHERE excluded.verified_at IS NOT NULL AND "
                "(listings.verified_at IS NULL OR excluded.verified_at > listings.verified_at)",
                [listing[field] for field in FIELDS],
            )
        merge_galleries(connection, snapshot["galleries"])
        merge_sources(connection, snapshot["sources"])
        if snapshot["last_run"] is not None:
            connection.execute("UPDATE metadata SET last_run = ? WHERE last_run IS NULL OR last_run < ?",
                               (snapshot["last_run"], snapshot["last_run"]))


def merge_galleries(connection, galleries):
    for url, paths in galleries.items():
        if not paths:
            continue
        for path in paths:
            relative = Path(path)
            if relative.parts[:2] != ("runtime", "images") or ".." in relative.parts:
                raise ValueError("Gallery must reference a local runtime/images file")
        # Existing immutable galleries remain intact when an older worker publishes.
        if connection.execute("SELECT 1 FROM galleries WHERE url = ?", (url,)).fetchone() is not None:
            continue
        connection.executemany("INSERT INTO galleries VALUES (?, ?, ?)",
                               [(url, position, path) for position, path in enumerate(paths)])


def merge_sources(connection, sources):
    for name, source in sources.items():
        connection.execute("""
            INSERT INTO sources VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET status=excluded.status, new=excluded.new,
                errors=excluded.errors, checked_at=excluded.checked_at
            WHERE excluded.checked_at > sources.checked_at
        """, (name, source["status"], source["new"], json.dumps(source["errors"], ensure_ascii=False), source["checked_at"]))


def validate_changes(changes):
    if not isinstance(changes, dict) or not changes or set(changes) - {"status", "notes"}:
        raise ValueError("Only status and notes can be edited")
    if "status" in changes and changes["status"] not in STATUSES:
        raise ValueError("Invalid status")
    if "notes" in changes and (not isinstance(changes["notes"], str) or len(changes["notes"]) > 10000):
        raise ValueError("Notes must be text up to 10000 characters")


def update_listing(path, url, changes):
    validate_changes(changes)
    assignments = ",".join(field + " = ?" for field in changes)
    with connect(path) as connection:
        cursor = connection.execute(f"UPDATE listings SET {assignments} WHERE url = ?", [*changes.values(), url])
        if cursor.rowcount != 1:
            raise KeyError("Listing not found")


def backup(source, destination):
    destination = Path(destination)
    with connect(source, "ro") as connection:
        with destination.open("xb"):
            pass
        try:
            target = sqlite3.connect(destination)
            try:
                connection.backup(target)
            finally:
                target.close()
        except Exception:
            destination.unlink()
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "merge"))
    parser.add_argument("database", type=Path)
    parser.add_argument("snapshot", type=Path)
    arguments = parser.parse_args()
    if arguments.action == "backup":
        backup(arguments.database, arguments.snapshot)
    else:
        merge(arguments.database, read(arguments.snapshot))
