"""Regression tests for qualification, identity, and repeated scans."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import worker


class WorkerTests(unittest.TestCase):
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
                worker.run(config)
                path = Path(directory) / "manifest.json"
                manifest = json.loads(path.read_text(encoding="utf8"))
                manifest["listings"]["Test:123456"]["status"] = "Ciekawe"
                manifest["listings"]["Test:123456"]["notes"] = "Zadzwonić"
                path.write_text(json.dumps(manifest), encoding="utf8")
                worker.run(config)
                after = json.loads(path.read_text(encoding="utf8"))
            self.assertEqual(len(after["listings"]), 1)
            self.assertEqual(after["listings"]["Test:123456"]["status"], "Ciekawe")
            self.assertEqual(after["listings"]["Test:123456"]["notes"], "Zadzwonić")

    def test_failed_image_transfer_does_not_publish_manifest(self):
        commands = []

        def fail_first(command, **kwargs):
            commands.append(command)
            raise RuntimeError("interrupted transfer")

        with patch.object(worker.subprocess, "run", side_effect=fail_first):
            with self.assertRaisesRegex(RuntimeError, "interrupted transfer"):
                worker.upload({"ssh_target": "worker@example", "remote_data_dir": "/srv/chata-data"}, Path("manifest.json"), Path("images"))
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
            path = Path(directory) / "manifest.json"
            saved = {"listings": {"Test:123456": {"status": "Ciekawe", "notes": "Zadzwonić"}}, "galleries": {}, "sources": {}}
            path.write_text(json.dumps(saved), encoding="utf8")
            with patch.dict(sys.modules, {"cloakbrowser": fake_module}), patch.object(worker, "ADAPTERS", (adapter,)):
                worker.run({"state_dir": directory})
            after = json.loads(path.read_text(encoding="utf8"))
            self.assertEqual(after["listings"], saved["listings"])
            self.assertEqual(after["sources"]["Test"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
