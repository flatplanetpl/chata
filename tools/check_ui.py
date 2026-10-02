"""Browser regression checks through Flask's test client, without starting a server."""

import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
import storage


def check_browser(client, database):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})

        def route_request(route):
            request = route.request
            response = client.open(urlsplit(request.url).path, method=request.method,
                                   data=request.post_data, content_type=request.headers.get("content-type"))
            route.fulfill(status=response.status_code, body=response.data, headers=dict(response.headers))

        context.route("**/*", route_request)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://chata.test/")
        expect(page.locator(".card")).to_have_count(2)
        unknown = page.locator(".card").filter(has_text="Nieznane parametry")
        known = page.locator(".card").filter(has=page.get_by_text("Znane parametry", exact=True))
        expect(unknown.locator(".metric b")).to_have_text(["—", "—", "—"])
        expect(known.locator(".metric b")).to_have_text(["68 m²", "1200 zł", "4700 zł"])
        assert len(unknown.locator(".description-preview").inner_text()) <= 181
        for width in (1440, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000})
            summary = unknown.locator(".listing-details summary")
            summary.focus()
            page.keyboard.press("Enter")
            expect(summary.locator(".less")).to_be_visible()
            expect(summary.locator(".more")).to_be_hidden()
            expect(unknown.locator(".description-preview")).to_be_hidden()
            expect(unknown.locator(".listing-details p").first).to_contain_text("KONIEC OPISU")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            summary.click()
            expect(unknown.locator(".description-preview")).to_be_visible()
        page.locator("#q").fill("KONIEC OPISU")
        expect(page.locator(".card")).to_have_count(1)
        check_visits(page, database)
        assert not errors, errors
        browser.close()


def check_visits(page, database):
    page.locator("#q").fill("")
    expect(page.locator(".card.since-visit")).to_have_count(0)
    expect(page.locator(".badge.new")).to_have_count(0)
    previous = page.evaluate("localStorage.getItem('chata-visited-listings')")
    assert len(json.loads(previous)) == 2
    listing = next(iter(storage.read(database)["listings"].values()))
    listing.update(id="Test:added", url="https://example.com/added", location="Dodane od wizyty", found="2000-01-01")
    storage.merge(database, {"listings": {listing["id"]: listing}, "galleries": {}, "sources": {}, "last_run": None})
    page.route("**/api/listings", lambda route: route.fulfill(status=503, body="Unavailable"))
    page.reload()
    expect(page.locator("#source")).to_contain_text("Nie udało się wczytać")
    assert page.evaluate("localStorage.getItem('chata-visited-listings')") == previous
    page.unroute("**/api/listings")
    page.reload()
    expect(page.locator(".card.since-visit")).to_have_count(1)
    expect(page.locator(".card.since-visit .badge.new")).to_have_text("Nowe od ostatniej wizyty")
    page.locator("#q").fill("Dodane od wizyty")
    expect(page.locator(".card.since-visit")).to_have_count(1)
    page.locator("#sort").select_option("rent")
    expect(page.locator(".card.since-visit")).to_have_count(1)
    page.reload()
    expect(page.locator(".card")).to_have_count(3)
    expect(page.locator(".card.since-visit")).to_have_count(0)
    page.evaluate("localStorage.setItem('chata-visited-listings', 'broken')")
    page.reload()
    expect(page.locator("#visitError")).to_contain_text("Nie można odczytać")
    expect(page.locator(".card")).to_have_count(3)
    assert page.evaluate("localStorage.getItem('chata-visited-listings')") == "broken"


def main():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "chata.sqlite3"
        storage.initialize(database)
        unknown = storage.new_listing({
            "id": "Test:unknown", "url": "https://example.com/unknown", "portal": "Test",
            "title": "Nieznane parametry", "location": "Nieznane parametry", "rent": 3500, "rooms": 3,
            "description": "Przestronne mieszkanie. " * 30 + "KONIEC OPISU <script>throw Error('unsafe')</script>",
            "found": "2026-10-02", "parameters": {
                "area": None, "fees": None, "total": None, "pets": "Brak info", "fee_details": ""},
        })
        known = {**unknown, "id": "Test:known", "url": "https://example.com/known",
                 "location": "Znane parametry", "description": "Krótki opis.", "area": 68, "fees": 1200, "total": 4700}
        storage.merge(database, {"listings": {"unknown": unknown, "known": known},
                                 "galleries": {}, "sources": {}, "last_run": None})
        check_browser(create_app(database).test_client(), database)
    print("PASS: descriptions, parameters, mobile, search, HTML escaping, visit highlights, reload, filters, failed load, invalid visit data")


if __name__ == "__main__":
    main()
