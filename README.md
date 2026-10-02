# Chata

Prywatny tracker mieszkań do wynajęcia dla Ołtaszyna i okolic.

## Dane i aplikacja

SQLite jest jedynym magazynem ofert, statusów, uwag, galerii i raportów źródeł. Flask udostępnia `GET /api/listings` oraz `PATCH /api/listings` (adres oferty i zmieniane pola `status` lub `notes`). Statusy i uwagi są wspólne dla wszystkich przeglądarek. Nieudany zapis jest sygnalizowany na stronie. Pliki zdjęć pozostają w katalogu `images`; API przechowuje ich ścieżki.

`storage.py` definiuje schemat wersji 1, transakcje, import wyników workera i spójne kopie przez SQLite Backup API. Publikacja dodaje nowe oferty i galerie, zachowuje ręczne dane oraz nie usuwa ofert przy błędzie portalu. Starszy raport nie zastępuje nowszego. Brak bazy albo niezgodny schemat zatrzymuje aplikację.

Karty pokazują skrót opisu do 180 znaków. „Pokaż szczegóły” rozwija pełny opis, liczbę pokoi, lokalizację i informacje o rozpoznanych opłatach; „Zwiń szczegóły” przywraca skrót. Brak wartości oznaczony jest „—”, bez zamiany na zero.

Worker zapisuje metraż, opłaty i informację o zwierzętach oraz odświeża istniejące oferty także wtedy, gdy mają już zdjęcia. Otodom dostarcza metraż i czynsz z pól `m` i `rent`; dla pozostałych adapterów parser rozpoznaje jednoznacznie opisane parametry w tytule/opisie. Niejednoznaczne lub niepodane wartości pozostają nieznane. Znany koszt razem obejmuje najem i rozpoznane opłaty; dodatkowe koszty parkingu czy prądu należy sprawdzić w pełnym opisie. Publikacja przyjmuje wyłącznie nowszą weryfikację oferty (`verified_at`) i zachowuje własne statusy, uwagi oraz datę znalezienia. Błąd odczytu źródła nie zmienia zapisanej oferty.

`data/initial.sqlite3` zawiera 26 ofert z dotychczasowego arkusza oraz 11 dostępnych w repozytorium galerii (152 ścieżki zdjęć). To baza początkowa dla nowej instalacji; nie zawiera dodatkowych ofert ani plików zdjęć istniejących wyłącznie na serwerze. Arkusz, manifest i localStorage nie są już odczytywane przez aplikację.

## Migracja istniejącej instalacji

Migrację wykonuje się przed wdrożeniem nowego obrazu i uruchomieniem nowego workera. Zatrzymaj dotychczasowy timer na czas migracji oraz zachowaj kopię `/srv/chata-data`, stanu workera i eksporty uwag z używanych przeglądarek. Nie zastępuj bazy produkcyjnej plikiem `data/initial.sqlite3`.

Jednorazowe narzędzie `tools/migrate_sqlite.py` odczytuje dawne pliki wyłącznie jako wejście migracji. W checkoutcie projektu można odzyskać wejścia z ostatniej rewizji sprzed SQLite:

```sh
mkdir -p /tmp/chata-migration
git show a4dc3b8809ad688ca8d20dd5fa1c529f3a59d016:data.xlsx > /tmp/chata-migration/data.xlsx
git show a4dc3b8809ad688ca8d20dd5fa1c529f3a59d016:legacy-galleries.json > /tmp/chata-migration/galleries.json
python3 tools/migrate_sqlite.py \
  --database /srv/chata-data/chata.sqlite3 \
  --workbook /tmp/chata-migration/data.xlsx \
  --galleries /tmp/chata-migration/galleries.json \
  --manifest /srv/chata-data/manifest.json
```

Należy użyć aktualnego manifestu z serwera, zawierającego oferty workera. Narzędzie publikuje bazę dopiero po poprawnym zakończeniu całego importu i odmawia nadpisania istniejącej bazy. Dotychczasowe pliki wejściowe oraz zdjęcia pozostają nienaruszone. Dla istniejącego workera wykonaj ten sam import do `/var/lib/chata-worker/chata.sqlite3`, wskazując jego lokalny manifest — zachowa to także oferty oczekujące na publikację.

Uwagi zapisane przed zmianą w localStorage są dostępne tylko w danej przeglądarce. W konsoli przeglądarki pod dotychczasowym adresem strony odczytaj `localStorage.getItem('chata-edits')` i zapisz zwrócony obiekt JSON do prywatnego pliku, np. `/tmp/chata-edits.json`. Następnie:

```sh
python3 tools/migrate_sqlite.py --database /srv/chata-data/chata.sqlite3 --browser-edits /tmp/chata-edits.json
```

Eksport musi być obiektem JSON, nie `null`. Import jest transakcyjny, zgłasza nieznane oferty i niepoprawne pola. Import z kolejnej przeglądarki zastąpi wskazane w nim pola — wcześniej uzgodnij ewentualne rozbieżności. Plików eksportu nie dodawaj do repozytorium.

Baza i jej katalog muszą być zapisywalne dla konta `chata-worker` na serwerze (SQLite tworzy obok bazy plik dziennika). Ustaw właściciela nowej bazy na to konto. Host aplikacji wymaga `python3` z modułem `sqlite3` do importu przez SSH.

## Nowa instalacja i kontener

Dla nowej, pustej instalacji utwórz katalog danych i wykonaj:

```sh
python3 storage.py backup data/initial.sqlite3 /srv/chata-data/chata.sqlite3
```

Polecenie odmawia nadpisania istniejącego pliku. Dostępne zdjęcia należy osobno umieścić w `/srv/chata-data/images`.

Kontener uruchamia Gunicorn na porcie 8080. `compose.yaml` montuje `/srv/chata-data` jako `/data` do odczytu i zapisu; `CHATA_DATABASE=/data/chata.sqlite3`. Port hosta `100.78.0.117:8088` jest związany z adresem Tailscale. API oraz obrazy przechodzą przez istniejące HTTP Basic w Traefik (`deploy/chata-traefik.example.yaml`). Plik bazy i skrypty nie są udostępniane przez HTTP.

Definicja Compose jest przeznaczona dla aplikacji Coolify `hws9lbkbogjvy9e7dhxvnjcc` na `lobster-dev01`. Zmiana repozytorium nie wdraża jej automatycznie w ramach lokalnej weryfikacji. Po migracji i wdrożeniu sprawdź logowanie, liczbę ofert, realne galerie oraz zapis uwagi w dwóch przeglądarkach.

## Worker na Linuxie w Tailscale

1. Sklonuj repozytorium na maszynie workera. `sudo sh worker/install-linux.sh` instaluje środowisko Python, CloakBrowser, `rsync`, klienta SSH i timer systemd. Istniejący stan JSON zmigruj przed instalacją, ponieważ skrypt włącza timer.
2. Ustaw `/etc/chata-worker/config.json` według `worker/config.example.json`. `state_dir` wskazuje `/var/lib/chata-worker`; `ssh_target` wskazuje konto `chata-worker@lobster-dev01` przez Tailscale.
3. Prywatny klucz SSH umieść wyłącznie w `/var/lib/chata-worker/.ssh/id_ed25519` na maszynie workera (właściciel `chata-worker`, tryb `0600`). Na serwerze dodaj klucz publiczny do `authorized_keys`. Zweryfikuj odcisk hosta przed dodaniem do `known_hosts`. Kluczy nie dodawaj do repozytorium.
4. Sprawdź `sudo -u chata-worker ssh -o BatchMode=yes chata-worker@lobster-dev01 true`, następnie `sudo systemctl start chata-worker.service` i `journalctl -u chata-worker.service -n 100 --no-pager`.

Timer wyszukuje oferty co 2 godziny z losowym opóźnieniem do 5 minut. Nowy worker pobiera przez SSH spójną kopię bazy serwera; brak bazy na serwerze jest błędem. Istniejący lokalny manifest bez zmigrowanej bazy także zatrzymuje workera. Uruchomienie bez `--publish` inicjalizuje nowy lokalny stan z `data/initial.sqlite3`.

Publikacja przesyła najpierw zdjęcia, potem osobną kopię SQLite i moduł importera. Dopiero poprawny transfer uruchamia transakcyjne scalenie na serwerze przez SSH. Aktywna baza serwera nie jest zastępowana kopią workera, dzięki czemu ręczne zmiany nie giną. Pliki transferu mają unikalne nazwy i są usuwane po zakończeniu. Po zerwaniu SSH mogą pozostać nieaktywne pliki `incoming-*`, `snapshot-*` lub `storage-*`; nie są odczytywane przez aplikację.

Kryteria: 3 pokoje, najem do 3700 zł, do 3 km od środka Ołtaszyna przy dostępnych współrzędnych; przy ich braku kwalifikacja według nazw pobliskich osiedli. Wyraźny zakaz zwierząt wyklucza ofertę. Każdy portal ma osobny adapter. Nieczytelne oferty trafiają do raportu źródła.

Klucz CloakBrowser, jeżeli potrzebny, ustaw w prywatnym systemd drop-in jako `CLOAKBROWSER_LICENSE_KEY`.

## Sprawdzenie

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s worker -v
python3 tools/check_ui.py
docker compose config --quiet
docker build -t chata:sqlite-local .
```

Testy obejmują import, współdzielenie statusów, równoległe zapisy, zachowanie ręcznych danych podczas publikacji, rollback, przerwanie transferu i błędy źródeł. Nie uruchamiają serwera ani prawdziwych wyszukiwań portali. Kopię działającej bazy wykonuj przez `python3 storage.py backup /srv/chata-data/chata.sqlite3 /ścieżka/do/nowej-kopii.sqlite3`.

`tools/check_ui.py` wymaga pakietu Python `playwright` i zainstalowanego Chromium. Sprawdza rozwijanie i zwijanie opisów klawiaturą, nieznane parametry, wyszukiwanie w pełnym opisie i widok 320/390/1440 px przez klienta testowego Flask, bez uruchamiania serwera.
