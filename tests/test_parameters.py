"""Only explicit apartment facts may populate the listing parameters."""

import unittest

from listing_parameters import from_text, from_otodom


class ParameterTests(unittest.TestCase):
    def test_apartment_area_does_not_use_terrace_or_room_area(self):
        parameters = from_text("Taras 30m2", "Mieszkanie o powierzchni 52,93 m². Salon 25m2.", 3200)
        self.assertEqual(parameters["area"], 52.93)
        self.assertIsNone(from_text("Taras 30m2", "Salon 25m2, sypialnia 10m2", 3200)["area"])

    def test_administration_fee_and_known_total_exclude_deposit(self):
        for description in (
            "Czynsz najmu: 3380 zł. Czynsz administracyjny: około 600 zł. Kaucja 7000 zł.",
            "3380 zł – czynsz najmu; 600 zł – czynsz administracyjny; kaucja 7000 zł.",
        ):
            with self.subTest(description=description):
                parameters = from_text("Mieszkanie", description, 3380)
                self.assertEqual((parameters["fees"], parameters["total"]), (600, 3980))
                self.assertIn("600", parameters["fee_details"])

    def test_unknown_is_not_zero_and_conflicting_fees_are_unknown(self):
        parameters = from_text("Mieszkanie", "Kaucja 4000 zł. Media według zużycia.", 3000)
        self.assertIsNone(parameters["fees"])
        self.assertIsNone(parameters["total"])
        self.assertEqual(parameters["pets"], "Brak info")
        self.assertIsNone(from_text("Mieszkanie", "Czynsz administracyjny 600 zł lub 900 zł.", 3000)["fees"])

    def test_pets_require_explicit_acceptance(self):
        self.assertEqual(from_text("Pet friendly", "", 3000)["pets"], "Tak")
        self.assertEqual(from_text("Mieszkanie", "Zwierzęta do uzgodnienia", 3000)["pets"], "Do uzgodnienia")
        self.assertEqual(from_text("Mieszkanie", "Zwierzęta nie są akceptowane", 3000)["pets"], "Nie")
        self.assertEqual(from_text("Mieszkanie", "W okolicy wybieg dla psów", 3000)["pets"], "Brak info")

    def test_otodom_reads_structured_area_and_fees(self):
        ad = {"title": "Taras 30m2", "description": "Salon 25m2", "characteristics": [
            {"key": "m", "value": "50"}, {"key": "rent", "value": "1000"},
        ]}
        parameters = from_otodom(ad, 3650)
        self.assertEqual((parameters["area"], parameters["fees"], parameters["total"]), (50, 1000, 4650))

    def test_otodom_missing_parameters_stay_unknown(self):
        ad = {"title": "Mieszkanie", "description": "Taras 30m2", "characteristics": []}
        parameters = from_otodom(ad, 3000)
        self.assertIsNone(parameters["area"])
        self.assertIsNone(parameters["fees"])
        self.assertIsNone(parameters["total"])
