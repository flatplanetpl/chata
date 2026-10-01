"""Search apartment portals and publish immutable images plus an atomic manifest."""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CENTER = (51.0616, 17.0168)
NEARBY = ("oltaszyn", "partynice", "klecina", "wojszyce", "wysoka", "karkonoska")
BLOCKED_PETS = re.compile(r"(?:bez|zakaz)\s+(?:zwierzat|kotow)|(?:zwierzeta|koty)\s+nie\s+(?:sa\s+)?akceptowane|nie\s+akceptujemy\s+(?:zwierzat|kotow)", re.I)


def normalized(value):
    value = value.replace("ł", "l").replace("Ł", "L")
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()


def distance_km(latitude, longitude):
    a1, o1 = map(math.radians, CENTER)
    a2, o2 = map(math.radians, (latitude, longitude))
    delta = math.sin((a2 - a1) / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin((o2 - o1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(delta))


def qualifies(listing):
    if listing["rooms"] != 3 or listing["rent"] > 3700 or listing["rent"] <= 0:
        return False
    if BLOCKED_PETS.search(normalized(listing["description"])):
        return False
    if listing["coordinates"] is not None:
        return distance_km(*listing["coordinates"]) <= 3
    return any(place in normalized(listing["location"]) for place in NEARBY)


class ListingHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.gallery_links = []
        self.meta = {}
        self.ld_json = []
        self.in_json = False
        self.json_text = ""
        self.script_id = None
        self.script_text = ""
        self.scripts = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
            if values.get("data-fancybox-group") == "gallery":
                self.gallery_links.append(values["href"])
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key] = values["content"]
        if tag == "script" and values.get("type") == "application/ld+json":
            self.in_json = True
            self.json_text = ""
        if tag == "script" and values.get("id") in ("__NUXT_DATA__", "__NEXT_DATA__"):
            self.script_id = values["id"]
            self.script_text = ""

    def handle_data(self, data):
        if self.in_json:
            self.json_text += data
        if self.script_id:
            self.script_text += data

    def handle_endtag(self, tag):
        if tag == "script" and self.in_json:
            self.in_json = False
            try:
                self.ld_json.append(json.loads(self.json_text))
            except json.JSONDecodeError:
                pass
        if tag == "script" and self.script_id:
            try:
                self.scripts[self.script_id] = json.loads(self.script_text)
            except json.JSONDecodeError:
                pass
            self.script_id = None


class Adapter:
    def __init__(self, name, host, search_url, link_pattern, id_pattern):
        self.name = name
        self.host = host
        self.search_url = search_url
        self.link_pattern = re.compile(link_pattern)
        self.id_pattern = re.compile(id_pattern)

    def listing_links(self, html):
        page = ListingHTML()
        page.feed(html)
        links = []
        for href in page.links:
            url = urllib.parse.urljoin(self.search_url, href).split("?")[0]
            if urllib.parse.urlparse(url).hostname in (self.host, "www." + self.host) and self.link_pattern.search(url):
                links.append(url)
        if not links:
            raise ValueError("No listing links; portal layout or access may have changed")
        return list(dict.fromkeys(links))

    def identity(self, url):
        match = self.id_pattern.search(urllib.parse.urlparse(url).path)
        if match is None:
            raise ValueError("Missing portal listing ID")
        return f"{self.name}:{match.group(1)}"

    def gallery(self, page):
        images = []
        for item in page.ld_json:
            for node in nodes(item):
                value = node.get("image")
                if isinstance(value, str):
                    images.append(value)
                elif isinstance(value, list):
                    images.extend(image for image in value if isinstance(image, str))
        for key in ("og:image", "twitter:image"):
            if key in page.meta:
                images.append(page.meta[key])
        return [url for url in dict.fromkeys(images) if url.startswith("https://")]

    def parse(self, url, html):
        page = ListingHTML()
        page.feed(html)
        title = page.meta.get("og:title", "")
        structured = list(node for item in page.ld_json for node in nodes(item))
        detail = next((node for node in structured if node.get("@type") in ("Product", "Offer")), {})
        description = unescape(re.sub(r"<[^>]+>", " ", detail.get("description", page.meta.get("og:description", ""))))
        text = normalized(title + " " + description)
        room_match = re.search(r"(\d+)\s*[- ]?\s*(?:pokoj|pok\.)", text)
        rent_match = re.search(r"(\d[\d\s]{2,6})\s*z[lł]", text)
        offer = detail.get("offers", detail)
        price = offer.get("price")
        if price is None and rent_match is not None:
            price = rent_match.group(1).replace(" ", "")
        if room_match is None or price is None:
            raise ValueError("Rooms or rent not found; listing needs review")
        location = page.meta.get("place:location:address", detail.get("name", title) + " " + description[:250])
        coordinates = None
        if "place:location:latitude" in page.meta and "place:location:longitude" in page.meta:
            coordinates = (float(page.meta["place:location:latitude"]), float(page.meta["place:location:longitude"]))
        return {
            "id": self.identity(url), "url": url, "portal": self.name,
            "title": title, "description": description, "location": location,
            "rooms": int(room_match.group(1)), "rent": int(float(str(price).replace(" ", "").replace(",", "."))),
            "coordinates": coordinates, "images": self.gallery(page),
        }


class OlxAdapter(Adapter):
    pass


class OtodomAdapter(Adapter):
    def parse(self, url, html):
        listing = super().parse(url, html)
        page = ListingHTML()
        page.feed(html)
        ad = page.scripts["__NEXT_DATA__"]["props"]["pageProps"]["ad"]
        listing["description"] = unescape(re.sub(r"<[^>]+>", " ", ad["description"]))
        listing["rooms"] = int(ad["target"]["Rooms_num"][0])
        listing["rent"] = int(next(item["value"] for item in ad["characteristics"] if item["key"] == "price"))
        coordinates = ad["location"]["coordinates"]
        listing["coordinates"] = (coordinates["latitude"], coordinates["longitude"])
        listing["location"] = ad["location"]["reverseGeocoding"]["locations"][-1]["fullName"]
        return listing

    def gallery(self, page):
        data = page.scripts.get("__NEXT_DATA__")
        if data:
            try:
                images = data["props"]["pageProps"]["ad"]["images"]
                return list(dict.fromkeys(image["large"] for image in images))
            except (KeyError, TypeError):
                pass
        return super().gallery(page)


class GratkaAdapter(Adapter):
    def gallery(self, page):
        data = page.scripts.get("__NUXT_DATA__")
        if data:
            try:
                listing = next(item for item in data if isinstance(item, dict) and "adKeywords" in item and "photos" in item)
                result = []
                for index in data[listing["photos"]]:
                    photo = data[index]
                    image_id = data[photo["id"]]
                    name = data[photo["name"]]
                    result.append(f"https://thumbs.cdngr.pl/thumb/{image_id}/3x2_l:fill_and_crop/{name}.jpg")
                return result
            except (KeyError, TypeError, StopIteration, IndexError):
                pass
        return super().gallery(page)


class MorizonAdapter(GratkaAdapter):
    pass


class OkolicaAdapter(Adapter):
    def gallery(self, page):
        return list(dict.fromkeys(page.gallery_links))

    def parse(self, url, html):
        page = ListingHTML()
        page.feed(html)
        detail = next(node for item in page.ld_json for node in nodes(item) if node.get("@type") == "RealEstateListing")
        description = page.meta["og:description"]
        match = re.search(r"(\d+)\s*[- ]?\s*pokoj", normalized(detail["description"]))
        if match is None:
            raise ValueError("Rooms missing from listing")
        return {
            "id": self.identity(url), "url": url, "portal": self.name,
            "title": detail["name"], "description": description,
            "location": detail["name"], "rooms": int(match.group(1)),
            "rent": int(float(detail["offers"]["price"])),
            "coordinates": None, "images": self.gallery(page),
        }


class DomiportaAdapter(Adapter):
    pass


ADAPTERS = (
    OlxAdapter("OLX", "olx.pl", "https://www.olx.pl/nieruchomosci/mieszkania/wynajem/wroclaw/q-o%C5%82taszyn/", r"/d/oferta/", r"-ID([A-Za-z0-9]+)"),
    OtodomAdapter("Otodom", "otodom.pl", "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/dolnoslaskie/wroclaw/wroclaw/wroclaw?query=O%C5%82taszyn", r"/pl/oferta/", r"-ID([A-Za-z0-9]+)"),
    GratkaAdapter("Gratka", "gratka.pl", "https://gratka.pl/nieruchomosci/mieszkania/wroclaw/oltaszyn/wynajem", r"/ob/\d+", r"/ob/(\d+)"),
    MorizonAdapter("Morizon", "morizon.pl", "https://www.morizon.pl/do-wynajecia/mieszkania/wroclaw/oltaszyn/", r"/oferta/", r"/oferta/[^/]*?(\d{6,})"),
    OkolicaAdapter("Okolica", "okolica.pl", "https://www.okolica.pl/mieszkanie/wynajme/wroclaw/oltaszyn/", r"/offer/show/", r"/offer/show/([^/]+)"),
    DomiportaAdapter("Domiporta", "domiporta.pl", "https://www.domiporta.pl/mieszkanie/wynajme/dolnoslaskie/wroclaw", r"/nieruchomosci/wynajme-", r"/(\d{6,})(?:/|$)"),
)


def nodes(item):
    if isinstance(item, list):
        for child in item:
            yield from nodes(child)
    elif isinstance(item, dict):
        yield item
        if "@graph" in item:
            yield from nodes(item["@graph"])


def legacy_urls():
    import xml.etree.ElementTree as ET
    import zipfile

    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(ROOT / "data.xlsx") as book:
        strings = ET.fromstring(book.read("xl/sharedStrings.xml"))
        values = ["".join(part.text or "" for part in item.findall(".//x:t", namespace)) for item in strings.findall("x:si", namespace)]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    urls = set()
    for cell in sheet.findall(".//x:sheetData/x:row/x:c", namespace):
        if not re.fullmatch(r"S\d+", cell.attrib["r"]):
            continue
        value = cell.find("x:v", namespace)
        if value is not None:
            url = values[int(value.text)] if cell.attrib.get("t") == "s" else value.text
            if url and url.startswith("https://"):
                urls.add(url.split("?")[0])
    return urls


def download_images(listing, image_root):
    paths = []
    for number, url in enumerate(listing["images"][:30]):
        name = hashlib.sha256((listing["id"] + "#" + str(number)).encode()).hexdigest()[:24] + ".jpg"
        path = image_root / name
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                if not response.headers.get("Content-Type", "").startswith("image/"):
                    raise ValueError("Gallery response is not an image")
                data = response.read(15_000_001)
            if len(data) < 1000 or len(data) > 15_000_000:
                raise ValueError("Invalid image size")
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(data)
            os.replace(temporary, path)
        paths.append("runtime/images/" + name)
    return paths


def record_issue(errors, adapter, field, url, error):
    issue = {field: url, "error": str(error)}
    errors.append(issue)
    print(json.dumps({"source": adapter.name, **issue}, ensure_ascii=False))


def scan_new(adapter, page, manifest, image_root, old_urls, errors):
    page.goto(adapter.search_url, wait_until="domcontentloaded", timeout=45000)
    links = adapter.listing_links(page.content())
    found = 0
    for url in links:
        if url in old_urls:
            continue
        try:
            identity = adapter.identity(url)
            if identity in manifest["listings"]:
                continue
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            listing = adapter.parse(url, page.content())
            if not qualifies(listing):
                continue
            images = download_images(listing, image_root)
            entry = {key: value for key, value in listing.items() if key not in ("images", "coordinates")}
            entry["found"] = datetime.now(timezone.utc).isoformat()
            manifest["listings"][identity] = entry
            manifest["galleries"][url] = images
            found += 1
        except Exception as error:
            record_issue(errors, adapter, "listing", url, error)
    return found


def backfill(adapter, page, manifest, image_root, old_urls, existing_galleries, errors):
    for url in old_urls:
        host = urllib.parse.urlparse(url).hostname
        if host not in (adapter.host, "www." + adapter.host):
            continue
        if url in existing_galleries or url in manifest["galleries"]:
            continue
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            detail = ListingHTML()
            detail.feed(page.content())
            images = adapter.gallery(detail)
            if not images:
                raise ValueError("No gallery images")
            manifest["galleries"][url] = download_images({"id": adapter.identity(url), "images": images}, image_root)
        except Exception as error:
            record_issue(errors, adapter, "legacy_gallery", url, error)


def scan_source(adapter, browser, manifest, image_root, old_urls, existing_galleries):
    page = browser.new_page()
    errors = []
    search_failed = False
    try:
        try:
            found = scan_new(adapter, page, manifest, image_root, old_urls, errors)
        except Exception as error:
            search_failed = True
            found = 0
            record_issue(errors, adapter, "search", adapter.search_url, error)
        backfill(adapter, page, manifest, image_root, old_urls, existing_galleries, errors)
    finally:
        page.close()
    status = "error" if search_failed else "partial" if errors else "ok"
    manifest["sources"][adapter.name] = {"status": status, "new": found, "errors": errors, "checked_at": datetime.now(timezone.utc).isoformat()}


def save_manifest(manifest, path):
    with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=path.parent, delete=False) as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        temporary = Path(output.name)
    os.replace(temporary, path)


def run(config, publish=False):
    from cloakbrowser import launch

    state_dir = Path(config["state_dir"])
    image_root = state_dir / "images"
    image_root.mkdir(parents=True, exist_ok=True)
    manifest_path = state_dir / "manifest.json"
    if publish and not manifest_path.exists():
        target = config["ssh_target"]
        remote = config["remote_data_dir"].rstrip("/")
        subprocess.run(["scp", "-q", f"{target}:{remote}/manifest.json", str(manifest_path)], check=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf8")) if manifest_path.exists() else {"listings": {}, "galleries": {}, "sources": {}}
    old_urls = legacy_urls()
    existing_galleries = json.loads((ROOT / "legacy-galleries.json").read_text(encoding="utf8"))
    browser = launch()
    try:
        for adapter in ADAPTERS:
            scan_source(adapter, browser, manifest, image_root, old_urls, existing_galleries)
    finally:
        browser.close()
    manifest["last_run"] = datetime.now(timezone.utc).isoformat()
    save_manifest(manifest, manifest_path)
    if publish:
        upload(config, manifest_path, image_root)
    print(json.dumps({"listings": len(manifest["listings"]), "sources": manifest["sources"]}, ensure_ascii=False))


def upload(config, manifest_path, image_root):
    target = config["ssh_target"]
    remote = config["remote_data_dir"].rstrip("/")
    subprocess.run(["rsync", "-a", "--ignore-existing", "--delay-updates", "--exclude=*.part", str(image_root) + "/", f"{target}:{remote}/images/"], check=True)
    subprocess.run(["scp", "-q", str(manifest_path), f"{target}:{remote}/manifest.json.part"], check=True)
    subprocess.run(["ssh", target, "mv", f"{remote}/manifest.json.part", f"{remote}/manifest.json"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args()
    run(json.loads(Path(arguments.config).read_text(encoding="utf8")), arguments.publish)
