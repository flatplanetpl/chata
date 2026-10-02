"""Extract explicit facts; unknown or ambiguous amounts remain NULL."""

import re
import unicodedata
from html import unescape


NUMBER = r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?"
FEE_LABEL = r"(?:czynsz administracyjny|oplaty administracyjne|zaliczka na media)"


def clean_text(value):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def normalize(value):
    value = value.lower().replace("ł", "l").replace("–", "-").replace("—", "-")
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


def number(value):
    result = float(re.sub(r"\s", "", str(value)).replace(",", "."))
    if not 0 <= result < 1_000_000:
        raise ValueError("Invalid listing parameter")
    return result


def pet_policy(text):
    if re.search(r"(?:bez|zakaz)\s+(?:zwierzat|kotow)|(?:zwierzeta|koty)\s+nie\s+(?:sa\s+)?akceptowane|nie\s+akceptujemy\s+(?:zwierzat|kotow)", text):
        return "Nie"
    if re.search(r"(?:zwierzeta|koty|kot)\s+do\s+uzgodnienia", text):
        return "Do uzgodnienia"
    if re.search(r"pet[- ]friendly|(?:zwierzeta|koty|kot)\s+(?:(?:sa|mile)\s+)?(?:akceptowane|widziane|dozwolone|ok)|akceptujemy\s+(?:zwierzeta|koty)", text):
        return "Tak"
    return "Brak info"


def apartment_area(title, description):
    # Require an apartment/area label, so a terrace or individual room is not used.
    pattern = rf"(?:powierzchni(?:a|e)?\s*[:~]?\s*|mieszkanie\s+(?:na wynajem\s+|do wynajecia[, ]+)?|mieszkanie\s+\d+-?pokojowe\s+)({NUMBER})\s*m2\b"
    values = {number(match.group(1)) for match in re.finditer(pattern, normalize(title + " " + description))}
    if len(values) == 1:
        return values.pop()
    return None


def text_fees(description):
    text = normalize(description)
    pattern = rf"(?:{FEE_LABEL})\s*[:–—-]?\s*(?:okolo\s+|ok\.\s*)?({NUMBER})\s*(?:zl|pln)"
    reverse = rf"({NUMBER})\s*(?:zl|pln)\s*[–—-]\s*(?:{FEE_LABEL})"
    matches = [*re.finditer(pattern, text), *re.finditer(reverse, text)]
    values = {number(match.group(1)) for match in matches}
    if len(values) != 1 or any(re.match(r"\s*(?:lub|[-–—])\s*\d", text[match.end():]) for match in matches):
        return None, ""
    return values.pop(), " • ".join(match.group() for match in matches)


def from_text(title, description, rent):
    title, description = clean_text(title), clean_text(description)
    fees, evidence = text_fees(description)
    return {
        "area": apartment_area(title, description), "fees": fees,
        "total": None if fees is None else rent + fees,
        "pets": pet_policy(normalize(title + " " + description)),
        "fee_details": evidence,
    }


def from_otodom(ad, rent):
    parameters = {"area": None, "fees": None, "total": None, "fee_details": "",
                  "pets": pet_policy(normalize(clean_text(ad["title"] + " " + ad["description"])))}
    for item in ad["characteristics"]:
        if item["key"] == "m":
            parameters["area"] = number(item["value"])
        if item["key"] == "rent":
            parameters["fees"] = number(item["value"])
            parameters["fee_details"] = "Czynsz administracyjny / media: " + item["value"] + " zł (parametr ogłoszenia)."
    if parameters["fees"] is not None:
        parameters["total"] = rent + parameters["fees"]
    return parameters
