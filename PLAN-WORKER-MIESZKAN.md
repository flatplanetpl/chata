# Worker wyszukiwania mieszkań i lokalnych galerii

## Idea

Co dwie godziny osobna maszyna Linux w Tailscale wyszukuje mieszkania na OLX, Otodom, Gratka, Morizon, Okolica i Domiporta. Nowe oferty spełniające kryteria trafiają do prywatnej strony ze statusem „Do sprawdzenia”. Zdjęcia są plikami lokalnymi; oferty i ręczne dane są przechowywane w SQLite.

## Przejście na SQLite — 2026-10-02

- [x] Zastąpić odczyt Excela, manifestu i localStorage wspólną bazą oraz API.
- [x] Przenieść 26 ofert i dostępne w repozytorium ścieżki galerii do `data/initial.sqlite3`.
- [x] Zapisywać stan workera w SQLite i scalać publikacje transakcyjnie przez SSH z zachowaniem ręcznych zmian.
- [x] Przygotować jednorazowy importer danych serwera i eksportów uwag z przeglądarek; instrukcja w [README.md](README.md#migracja-istniejącej-instalacji).
- [x] Sprawdzić lokalnie testy, zapis przez API w Chromium i budowę obrazu Docker.
- [ ] Zmigrować aktualne dane serwera i istniejącego workera, przenieść uwagi z używanych przeglądarek oraz wdrożyć nowy obraz.

Poniższy postęp i weryfikacja opisują wcześniejsze wdrożenie z 2026-10-01, sprzed SQLite.

## Postęp

- [x] Zapisać plan w projekcie.
- [x] Zbudować workera CloakBrowser z osobnymi adapterami sześciu portali, kwalifikacją ofert, deduplikacją i raportem źródeł.
- [x] Przenieść dostępne galerie dotychczasowych ofert do lokalnych plików przed usunięciem starego skryptu.
- [x] Połączyć arkusz z manifestem nowych ofert w aplikacji, zachowując ręczne statusy i uwagi.
- [x] Przygotować instalację Linux, timer co dwie godziny i atomowe przekazywanie danych przez SSH w Tailscale.
- [x] Przygotować trwały katalog danych, definicję montażu Coolify i trasę Traefik z HTTP Basic.
- [x] Sprawdzić testy jednostkowe, próbki wyszukiwania i galerii sześciu portali, oraz niepełny transfer manifestu.
- [ ] Zainstalować workera na maszynie Linux użytkownika i sprawdzić dwa uruchomienia timera.
- [x] Uruchomić aplikację przez Coolify, włączyć hasło HTTP Basic i sprawdzić `https://chata.kveik.pl` oraz trwałość po ponownym wdrożeniu.

## Kryteria

3 pokoje, najem najwyżej 3700 zł, Ołtaszyn i okolice około 3 km, brak wyraźnego zakazu kota. Sekrety pozostają poza repozytorium. Worker zapisuje dane na serwerze wyłącznie przez SSH.

## Weryfikacja lokalna — 2026-10-01

- `python -m unittest discover -s worker -v`: 5 testów zakończonych powodzeniem.
- CloakBrowser odczytał wyszukiwanie, ofertę i galerię z każdego z sześciu portali; pobranie przykładowego zdjęcia z każdego źródła powiodło się.
- `/srv/chata-data` na `lobster-dev01`: 13 nowych ofert, 24 galerie workera, 399 plików zdjęć łącznie z migracją dawnych galerii. Każda ścieżka w manifeście workera wskazuje istniejący plik.
- Cztery dawne ogłoszenia nie udostępniały już galerii: dwa OLX aktywne/do weryfikacji, jedno OLX nieaktualne i jedno Gratka do weryfikacji.
- Obraz Docker zbudował się na serwerze; `docker compose config` oraz składnia timera systemd zostały sprawdzone bez uruchamiania aplikacji.
- Aplikacja Coolify `hws9lbkbogjvy9e7dhxvnjcc` działa na `lobster-dev01`, port hosta jest związany tylko z `100.78.0.117:8088`, a montaż `/srv/chata-data` ma `RW=false`.
- Publiczne żądanie bez hasła zwraca 401, z hasłem 200. Przeglądarka pokazuje 39 ofert i 35 galerii; zdjęcie w galerii ładuje się, ręczny status pozostaje po odświeżeniu. Po ponownym wdrożeniu obraz nadal zwraca 200 i 399 plików pozostaje na serwerze.
- Tymczasowe hasło strony jest przechowywane wyłącznie na serwerze `coolify` w `/data/coolify/chata/initial-password` (tryb 0600), poza repozytorium.
