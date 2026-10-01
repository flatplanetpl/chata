# Worker wyszukiwania mieszkań i lokalnych galerii

## Idea

Co dwie godziny osobna maszyna Linux w Tailscale wyszukuje mieszkania na OLX, Otodom, Gratka, Morizon, Okolica i Domiporta. Nowe oferty spełniające kryteria trafiają do prywatnej strony ze statusem „Do sprawdzenia”. Zdjęcia są plikami lokalnymi, a dotychczasowy arkusz pozostaje źródłem ręcznych danych.

## Postęp

- [x] Zapisać plan w projekcie.
- [x] Zbudować workera CloakBrowser z osobnymi adapterami sześciu portali, kwalifikacją ofert, deduplikacją i raportem źródeł.
- [x] Przenieść dostępne galerie dotychczasowych ofert do lokalnych plików przed usunięciem starego skryptu.
- [x] Połączyć arkusz z manifestem nowych ofert w aplikacji, zachowując ręczne statusy i uwagi.
- [x] Przygotować instalację Linux, timer co dwie godziny i atomowe przekazywanie danych przez SSH w Tailscale.
- [x] Przygotować trwały katalog danych, definicję montażu Coolify i trasę Traefik z HTTP Basic.
- [x] Sprawdzić testy jednostkowe, próbki wyszukiwania i galerii sześciu portali, oraz niepełny transfer manifestu.
- [ ] Zainstalować workera na maszynie Linux użytkownika i sprawdzić dwa uruchomienia timera.
- [ ] Uruchomić aplikację przez Coolify, włączyć hasło HTTP Basic i sprawdzić `https://chata.kveik.pl` oraz trwałość po ponownym wdrożeniu.

## Kryteria

3 pokoje, najem najwyżej 3700 zł, Ołtaszyn i okolice około 3 km, brak wyraźnego zakazu kota. Sekrety pozostają poza repozytorium. Worker zapisuje dane na serwerze wyłącznie przez SSH.
