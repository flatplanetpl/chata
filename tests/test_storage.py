"""SQLite persistence, publication and API regression tests."""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import storage
from app import create_app


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "chata.sqlite3"
        storage.initialize(self.database)
        self.entry = storage.new_listing({
            "id": "Test:123", "url": "https://example.com/123", "portal": "Test",
            "title": "Mieszkanie", "description": "Kot OK", "location": "Ołtaszyn",
            "rent": 3500, "rooms": 3, "found": "2026-10-02T00:00:00+00:00",
        })
        self.snapshot = {
            "listings": {self.entry["id"]: self.entry},
            "galleries": {self.entry["url"]: ["runtime/images/test.jpg"]},
            "sources": {"Test": {"status": "ok", "new": 1, "errors": [], "checked_at": "2026-10-02T00:00:00+00:00"}},
            "last_run": "2026-10-02T00:00:00+00:00",
        }
        storage.merge(self.database, self.snapshot)

    def test_repeated_publication_preserves_manual_edits_and_other_listings(self):
        storage.update_listing(self.database, self.entry["url"], {"status": "Ciekawe", "notes": "Zadzwonić"})
        storage.merge(self.database, self.snapshot)
        after = storage.read(self.database)
        self.assertEqual(len(after["listings"]), 1)
        self.assertEqual(after["listings"]["Test:123"]["status"], "Ciekawe")
        self.assertEqual(after["listings"]["Test:123"]["notes"], "Zadzwonić")
        storage.merge(self.database, {"listings": {}, "galleries": {}, "sources": {}, "last_run": None})
        self.assertEqual(storage.read(self.database), after)

    def test_failed_merge_rolls_back_the_entire_batch(self):
        self.snapshot["sources"]["Test"]["status"] = "broken"
        self.snapshot["galleries"][self.entry["url"]] = ["runtime/images/new.jpg"]
        with self.assertRaises(sqlite3.IntegrityError):
            storage.merge(self.database, self.snapshot)
        self.assertEqual(storage.read(self.database)["galleries"][self.entry["url"]], ["runtime/images/test.jpg"])

    def test_backup_is_consistent_and_does_not_need_wal_files(self):
        destination = Path(self.directory.name) / "snapshot.sqlite3"
        storage.backup(self.database, destination)
        self.assertEqual(storage.read(destination), storage.read(self.database))

    def test_missing_database_is_an_error(self):
        with self.assertRaises(sqlite3.OperationalError):
            storage.read(Path(self.directory.name) / "missing.sqlite3")
        self.assertFalse((Path(self.directory.name) / "missing.sqlite3").exists())
        with self.assertRaises(sqlite3.OperationalError):
            storage.backup(Path(self.directory.name) / "missing.sqlite3", Path(self.directory.name) / "backup.sqlite3")
        self.assertFalse((Path(self.directory.name) / "backup.sqlite3").exists())

    def test_api_edits_are_visible_to_another_client(self):
        application = create_app(self.database, Path(self.directory.name))
        first, second = application.test_client(), application.test_client()
        response = first.patch("/api/listings", json={"url": self.entry["url"], "notes": "Wspólna uwaga"})
        self.assertEqual(response.status_code, 200)
        row = second.get("/api/listings").get_json()["listings"]["Test:123"]
        self.assertEqual(row["notes"], "Wspólna uwaga")
        self.assertEqual(first.patch("/api/listings", json={"url": self.entry["url"], "status": "wrong"}).status_code, 400)
        self.assertEqual(first.patch("/api/listings", json={"url": self.entry["url"], "rent": 1}).status_code, 400)
        self.assertEqual(first.patch("/api/listings", json={"url": "https://example.com/missing", "notes": "x"}).status_code, 404)

    def test_database_and_internal_files_are_not_public(self):
        client = create_app(self.database, Path(self.directory.name)).test_client()
        for path in ("/runtime/chata.sqlite3", "/storage.py", "/data/initial.sqlite3", "/runtime/images/../chata.sqlite3"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_parallel_publication_and_independent_edits_do_not_lose_data(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(storage.merge, self.database, self.snapshot),
                executor.submit(storage.update_listing, self.database, self.entry["url"], {"status": "Ciekawe"}),
                executor.submit(storage.update_listing, self.database, self.entry["url"], {"notes": "Zadzwonić"}),
            ]
            for future in futures:
                future.result()
        after = storage.read(self.database)["listings"]["Test:123"]
        self.assertEqual((after["status"], after["notes"]), ("Ciekawe", "Zadzwonić"))

    def test_older_worker_report_cannot_replace_newer_report(self):
        self.snapshot["sources"]["Test"].update(checked_at="2026-10-01T00:00:00+00:00", status="error")
        self.snapshot["last_run"] = "2026-10-01T00:00:00+00:00"
        storage.merge(self.database, self.snapshot)
        after = storage.read(self.database)
        self.assertEqual(after["sources"]["Test"]["status"], "ok")
        self.assertEqual(after["last_run"], "2026-10-02T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
