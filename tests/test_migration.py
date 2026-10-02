"""One-time migration correctness and all-or-nothing browser import."""

import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import storage
from tools.migrate_sqlite import HEADERS, import_browser_edits, migrate


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "chata.sqlite3"
        self.workbook = self.root / "input.xlsx"
        self.galleries = self.root / "galleries.json"
        self.manifest = self.root / "manifest.json"
        self.url = "https://example.com/sheet"
        values = [46295, None, "TAK", "Ciekawe", "Aktywne", "Ołtaszyn", "Test", 3500,
                  None, None, 65, 3, "Tak", "balkon", "Opis", "", "Zadzwonić", self.url, 46295]
        rows = []
        for number, values in enumerate((list(HEADERS), values), 1):
            cells = []
            for index, value in enumerate(values):
                kind = "n" if isinstance(value, int) else "str"
                body = "" if value is None else "<v>" + escape(str(value)) + "</v>"
                cells.append(f'<c r="{chr(65 + index)}{number}" t="{kind}">{body}</c>')
            rows.append("<row>" + "".join(cells) + "</row>")
        with zipfile.ZipFile(self.workbook, "w") as book:
            book.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
            book.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(rows) + '</sheetData></worksheet>')
        self.galleries.write_text(json.dumps({self.url: ["runtime/images/sheet.jpg"]}))
        self.worker_listing = {"id": "Test:123", "url": "https://example.com/worker", "portal": "Test",
                               "title": "Nowa oferta", "description": "Kot OK", "location": "Ołtaszyn",
                               "rooms": 3, "rent": 3600, "found": "2026-10-01", "notes": "Notatka workera"}
        self.manifest.write_text(json.dumps({"listings": {"Test:123": self.worker_listing},
                                            "galleries": {}, "sources": {}, "last_run": "2026-10-01"}))

    def test_import_preserves_sheet_worker_and_manual_data(self):
        migrate(self.database, self.workbook, self.galleries, self.manifest)
        snapshot = storage.read(self.database)
        self.assertEqual(len(snapshot["listings"]), 2)
        sheet = next(row for row in snapshot["listings"].values() if row["url"] == self.url)
        self.assertEqual(sheet["found"], "2026-09-30")
        self.assertIsNone(sheet["total"])
        self.assertEqual(sheet["notes"], "Zadzwonić")
        self.assertEqual(snapshot["listings"]["Test:123"]["notes"], "Notatka workera")
        self.assertEqual(snapshot["galleries"][self.url], ["runtime/images/sheet.jpg"])
        with self.assertRaises(FileExistsError):
            migrate(self.database, self.workbook, self.galleries, self.manifest)
        self.assertEqual(storage.read(self.database), snapshot)

    def test_invalid_migration_does_not_leave_empty_database(self):
        self.galleries.write_text(json.dumps({"https://unknown.example": ["runtime/images/x.jpg"]}))
        with self.assertRaises(sqlite3.IntegrityError):
            migrate(self.database, self.workbook, self.galleries, self.manifest)
        self.assertFalse(self.database.exists())

    def test_browser_export_is_transactional(self):
        migrate(self.database, self.workbook, self.galleries, self.manifest)
        edits = self.root / "edits.json"
        edits.write_text(json.dumps({self.url: {"notes": "Nowa uwaga"}, "https://missing.example": {"notes": "x"}}))
        before = storage.read(self.database)
        with self.assertRaises(ValueError):
            import_browser_edits(self.database, edits)
        self.assertEqual(storage.read(self.database), before)
        edits.write_text(json.dumps({self.url: {"notes": "Nowa uwaga", "status": "Obejrzane"}}))
        import_browser_edits(self.database, edits)
        sheet = next(row for row in storage.read(self.database)["listings"].values() if row["url"] == self.url)
        self.assertEqual((sheet["notes"], sheet["status"]), ("Nowa uwaga", "Obejrzane"))


if __name__ == "__main__":
    unittest.main()
