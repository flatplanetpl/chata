"""One-time import of the former workbook, galleries, manifest and browser export."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import storage


NAMESPACE = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = {
    "Data znalezienia": "found", "Data ogłoszenia": "listing_date", "Nowe?": "fresh",
    "Status": "status", "Aktywność": "activity", "Lokalizacja / ulica": "location",
    "Portal": "portal", "Najem [zł]": "rent", "Opłaty znane [zł]": "fees",
    "Znany koszt razem [zł]": "total", "Metraż [m²]": "area", "Pokoje": "rooms",
    "Kot / zwierzęta": "pets", "Dodatki": "extras", "Krótki opis / atuty": "description",
    "Szczegóły opłat": "fee_details", "Uwagi własne": "notes", "Link": "url",
    "Ostatnia weryfikacja": "verified_at",
}
TEXT_FIELDS = {"fresh", "extras", "description", "fee_details", "notes"}


def cell_value(cell, strings):
    value = cell.find("x:v", NAMESPACE)
    if value is None or value.text is None:
        return None
    kind = cell.attrib["t"] if "t" in cell.attrib else "n"
    if kind == "s":
        return strings[int(value.text)]
    if kind == "n":
        return float(value.text)
    if kind == "str":
        return value.text
    raise ValueError("Unsupported workbook cell type: " + kind)


def workbook_rows(path):
    with zipfile.ZipFile(path) as book:
        shared = ET.fromstring(book.read("xl/sharedStrings.xml"))
        strings = ["".join(item.itertext()) for item in shared.findall("x:si", NAMESPACE)]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    headers = None
    for row in sheet.findall(".//x:sheetData/x:row", NAMESPACE):
        cells = {"".join(filter(str.isalpha, cell.attrib["r"])): cell_value(cell, strings)
                 for cell in row.findall("x:c", NAMESPACE)}
        if "Data znalezienia" in cells.values() and "Link" in cells.values():
            headers = {column: HEADERS[value] for column, value in cells.items() if value in HEADERS}
            continue
        if headers is not None:
            yield convert_row({field: cells[column] if column in cells else None for column, field in headers.items()})
    if headers is None:
        raise ValueError("Workbook listing table not found")


def convert_row(row):
    for field in ("found", "listing_date", "verified_at"):
        if isinstance(row[field], (float, int)):
            row[field] = (datetime(1899, 12, 30) + timedelta(days=row[field])).date().isoformat()
    for field in TEXT_FIELDS:
        if row[field] is None:
            row[field] = ""  # An empty spreadsheet text cell is stored as empty text.
    row["url"] = row["url"].split("?")[0]
    row["id"] = "import:" + hashlib.sha256(row["url"].encode()).hexdigest()[:24]
    row["title"] = row["location"]
    return row


def import_browser_edits(database, path):
    edits = json.loads(Path(path).read_text(encoding="utf8"))
    # A single transaction prevents partially importing an invalid export.
    with storage.connect(database) as connection:
        for url, changes in edits.items():
            storage.validate_changes(changes)
            assignments = ",".join(field + " = ?" for field in changes)
            cursor = connection.execute(f"UPDATE listings SET {assignments} WHERE url = ?",
                                        [*changes.values(), url.split("?")[0]])
            if cursor.rowcount != 1:
                raise ValueError("Browser export references an unknown listing: " + url)


def migrate(database, workbook, galleries, manifest):
    snapshot = {"listings": {}, "galleries": {}, "sources": {}, "last_run": None}
    for row in workbook_rows(workbook):
        snapshot["listings"][row["id"]] = row
    snapshot["galleries"] = json.loads(Path(galleries).read_text(encoding="utf8"))
    previous = json.loads(Path(manifest).read_text(encoding="utf8"))
    known_urls = {row["url"] for row in snapshot["listings"].values()}
    for listing in previous["listings"].values():
        if listing["url"] in known_urls:
            continue
        entry = storage.new_listing(listing)
        for field in ("status", "notes"):
            if field in listing:
                entry[field] = listing[field]
        snapshot["listings"][entry["id"]] = entry
        known_urls.add(entry["url"])
    snapshot["galleries"].update(previous["galleries"])
    snapshot["sources"] = previous["sources"]
    snapshot["last_run"] = previous["last_run"]
    with tempfile.TemporaryDirectory(dir=Path(database).parent) as directory:
        temporary = Path(directory) / "migration.sqlite3"
        storage.initialize(temporary)
        storage.merge(temporary, snapshot)
        # Publish only a complete database, and refuse to overwrite an existing one.
        os.link(temporary, database)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--galleries", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--browser-edits", type=Path)
    args = parser.parse_args()
    inputs = (args.workbook, args.galleries, args.manifest)
    if any(value is not None for value in inputs):
        if any(value is None for value in inputs):
            parser.error("--workbook, --galleries and --manifest must be supplied together")
        migrate(args.database, *inputs)
    elif args.browser_edits is None:
        parser.error("Supply workbook inputs or --browser-edits")
    if args.browser_edits is not None:
        import_browser_edits(args.database, args.browser_edits)
    print(json.dumps({"database": str(args.database), "listings": len(storage.read(args.database)["listings"])}, ensure_ascii=False))
