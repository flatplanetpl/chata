"""Regression tests for qualification, identity, and repeated scans."""

import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import worker
import storage


class WorkerTests(unittest.TestCase):
    def test_existing_gallery_does_not_prevent_parameter_refresh(self):
        url = "https://example.com/offer/123456"
        entry = storage.new_listing({"id": "Test:123456", "url": url, "portal": "Test",
            "title": "Mieszkanie", "description": "Opis", "location": "Ołtaszyn", "rooms": 3,
            "rent": 3500, "found": "2026-10-01", "parameters": {
                "area": None, "fees": None, "total": None, "pets": "Brak info", "fee_details": ""}})
        entry.update(status="Ciekawe", notes="Zadzwonić")
        snapshot = {"listings": {entry["id"]: entry}, "galleries": {url: ["runtime/images/saved.jpg"]}}
        html = '<meta property="og:title" content="3 pokoje Ołtaszyn 3500 zł"><meta property="og:description" content="Mieszkanie o powierzchni 68 m². Czynsz administracyjny 1200 zł.">'
        page = types.SimpleNamespace(goto=lambda *args, **kwargs: None, content=lambda: html)
        adapter = worker.Adapter("Test", "example.com", "https://example.com/search", r"/offer/", r"/offer/(\d+)")
        errors = []
        worker.backfill(adapter, page, snapshot, Path("images"), {url}, errors)
        self.assertEqual(errors, [])
        self.assertEqual((entry["area"], entry["fees"], entry["total"]), (68, 1200, 4700))
        self.assertEqual((entry["status"], entry["notes"]), ("Ciekawe", "Zadzwonić"))
        self.assertEqual(snapshot["galleries"][url], ["runtime/images/saved.jpg"])
        self.assertIsNotNone(entry["verified_at"])
        previous = dict(entry)
        page.content = lambda: '<meta property="og:title" content="3 pokoje Ołtaszyn 3500 zł"><meta property="og:description" content="Niepełny opis">'
        worker.backfill(adapter, page, snapshot, Path("images"), {url}, errors)
        self.assertEqual(entry, previous)
        self.assertTrue(errors)

    def test_qualification(self):
        listing = {"rooms": 3, "rent": 3700, "description": "Kot do uzgodnienia", "location": "Ołtaszyn", "coordinates": None}
        self.assertTrue(worker.qualifies(listing))
        self.assertFalse(worker.qualifies({**listing, "rent": 3701}))
        self.assertFalse(worker.qualifies({**listing, "rooms": 2}))
        self.assertFalse(worker.qualifies({**listing, "description": "Bez zwierząt"}))
        self.assertFalse(worker.qualifies({**listing, "location": "Szczepin"}))
        self.assertFalse(worker.qualifies({**listing, "coordinates": (51.11, 17.02)}))

    def test_portal_ids(self):
        urls = [
            "https://www.olx.pl/d/oferta/x-ID1cjKQS.html",
            "https://www.otodom.pl/pl/oferta/x-ID4D1SG",
            "https://gratka.pl/nieruchomosci/x/ob/49141543",
            "https://www.morizon.pl/oferta/x-mzn2048133096",
            "https://www.okolica.pl/offer/show/30667-W-43948/formular",
            "https://www.domiporta.pl/nieruchomosci/wynajme-mieszkanie-x/156409590",
        ]
        for adapter, url in zip(worker.ADAPTERS, urls):
            with self.subTest(portal=adapter.name):
                self.assertTrue(adapter.identity(url).startswith(adapter.name + ":"))

    def test_two_runs_keep_one_listing_and_manual_data(self):
        search = '<a href="https://example.com/offer/123456">listing</a>'
        detail = '<meta property="og:title" content="3 pokoje Ołtaszyn 3500 zł"><meta property="og:description" content="Ołtaszyn, kot do uzgodnienia">'

        class Page:
            def goto(self, url, **kwargs):
                self.html = detail if "offer" in url else search

            def content(self):
                return self.html

            def close(self):
                pass

        class Browser:
            def new_page(self):
                return Page()

            def close(self):
                pass

        fake_module = types.ModuleType("cloakbrowser")
        fake_module.launch = Browser
        adapter = worker.Adapter("Test", "example.com", "https://example.com/search", r"/offer/", r"/offer/(\d+)")
        with tempfile.TemporaryDirectory() as directory:
            config = {"state_dir": directory}
            with patch.dict(sys.modules, {"cloakbrowser": fake_module}), patch.object(worker, "ADAPTERS", (adapter,)), patch.object(worker, "download_images", return_value=[]):
                path = Path(directory) / "chata.sqlite3"
                storage.initialize(path)
                worker.run(config)
                storage.update_listing(path, "https://example.com/offer/123456", {"status": "Ciekawe", "notes": "Zadzwonić"})
                worker.run(config)
                after = storage.read(path)
            self.assertEqual(len(after["listings"]), 1)
            self.assertEqual(after["listings"]["Test:123456"]["status"], "Ciekawe")
            self.assertEqual(after["listings"]["Test:123456"]["notes"], "Zadzwonić")

    def test_failed_image_transfer_does_not_publish_database(self):
        commands = []

        def fail_first(command, **kwargs):
            commands.append(command)
            raise RuntimeError("interrupted transfer")

        with patch.object(worker.subprocess, "run", side_effect=fail_first):
            with self.assertRaisesRegex(RuntimeError, "interrupted transfer"):
                worker.upload({"ssh_target": "worker@example", "remote_data_dir": "/srv/chata-data"}, Path("chata.sqlite3"), Path("images"))
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0], "rsync")

    def test_blocked_search_keeps_saved_listings(self):
        class Page:
            def goto(self, url, **kwargs):
                pass

            def content(self):
                return "<html>Access denied</html>"

            def close(self):
                pass

        class Browser:
            def new_page(self):
                return Page()

            def close(self):
                pass

        fake_module = types.ModuleType("cloakbrowser")
        fake_module.launch = Browser
        adapter = worker.Adapter("Test", "example.com", "https://example.com/search", r"/offer/", r"/offer/(\d+)")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chata.sqlite3"
            storage.initialize(path)
            entry = storage.new_listing({"id": "Test:123456", "url": "https://example.com/offer/123456",
                "title": "Test", "description": "Kot OK", "portal": "Test", "location": "Ołtaszyn",
                "rooms": 3, "rent": 3500, "found": "2026-10-01",
                "parameters": {"area": None, "fees": None, "total": None, "pets": "Tak", "fee_details": ""}})
            entry.update(status="Ciekawe", notes="Zadzwonić")
            saved = {"listings": {entry["id"]: entry}, "galleries": {}, "sources": {}, "last_run": None}
            storage.merge(path, saved)
            with patch.dict(sys.modules, {"cloakbrowser": fake_module}), patch.object(worker, "ADAPTERS", (adapter,)):
                worker.run({"state_dir": directory})
            after = storage.read(path)
            self.assertEqual(after["listings"], saved["listings"])
            self.assertEqual(after["sources"]["Test"]["status"], "error")

    def test_publication_merges_snapshot_without_replacing_server_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "server data"
            remote.mkdir()
            server_database = remote / "chata.sqlite3"
            local_database = root / "worker.sqlite3"
            storage.backup(worker.ROOT / "data" / "initial.sqlite3", server_database)
            storage.backup(server_database, local_database)
            listing = next(iter(storage.read(server_database)["listings"].values()))
            storage.update_listing(server_database, listing["url"], {"notes": "Server edit"})
            commands = []
            real_run = subprocess.run

            def transport(command, **kwargs):
                commands.append(command)
                if command[0] == "rsync":
                    return
                if command[0] == "scp":
                    shutil.copyfile(command[2], command[3].split(":", 1)[1])
                    return
                self.assertEqual(command[0], "ssh")
                real_run(shlex.split(command[2]), **kwargs)

            config = {"ssh_target": "worker@example", "remote_data_dir": str(remote)}
            with patch.object(worker.subprocess, "run", side_effect=transport):
                worker.upload(config, local_database, root / "images")
            after = storage.read(server_database)["listings"][listing["id"]]
            self.assertEqual(after["notes"], "Server edit")
            self.assertEqual(commands[0][0], "rsync")
            self.assertEqual(list(remote.iterdir()), [server_database])

    def test_interrupted_database_transfer_never_runs_import(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "worker.sqlite3"
            storage.backup(worker.ROOT / "data" / "initial.sqlite3", database)
            commands = []

            def transport(command, **kwargs):
                commands.append(command)
                if command[0] == "scp":
                    raise RuntimeError("interrupted database transfer")

            with patch.object(worker.subprocess, "run", side_effect=transport):
                with self.assertRaisesRegex(RuntimeError, "interrupted database transfer"):
                    worker.upload({"ssh_target": "worker@example", "remote_data_dir": "/srv/chata-data"}, database, Path(directory))
            self.assertFalse(any(command[0] == "ssh" and "python3" in command[2] for command in commands))


if __name__ == "__main__":
    unittest.main()
