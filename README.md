# Chata

Prywatny tracker mieszkań do wynajęcia dla Ołtaszyna i okolic.

## Dane

`data.xlsx` pozostaje źródłem 26 dotychczasowych ofert. `legacy-galleries.json` wskazuje lokalne pliki zdjęć, które zostały skopiowane do `/srv/chata-data/images` na `lobster-dev01`. Worker zapisuje nowe oferty i galerie w `/srv/chata-data/manifest.json` oraz `/srv/chata-data/images`. Strona łączy oba źródła. Ręczne statusy i uwagi są przechowywane w `localStorage` przeglądarki, pod adresem ogłoszenia; dlatego nie są widoczne w innym profilu przeglądarki.

Kryteria workera: 3 pokoje, najem do 3700 zł, do 3 km od środka Ołtaszyna, gdy ogłoszenie ma współrzędne. Gdy ich nie ma, używa nazw pobliskich osiedli. Ogłoszenia z wyraźnym zakazem zwierząt są odrzucane. Każdy portal ma osobny adapter. Nieczytelne oferty trafiają do raportu błędów źródła; ich brak nie usuwa zapisanych ofert ani zdjęć.

## Worker na Linuxie w Tailscale

1. Sklonuj repozytorium na maszynie workera. Uruchom `sudo sh worker/install-linux.sh`. Skrypt instaluje środowisko Python, CloakBrowser, `rsync`, klienta SSH i timer systemd.
2. Ustaw `/etc/chata-worker/config.json` według `worker/config.example.json`. `state_dir` pozostaw jako `/var/lib/chata-worker`; `ssh_target` powinien wskazywać konto `chata-worker@lobster-dev01` przez Tailscale.
3. Wgraj prywatny klucz SSH wyłącznie do `/var/lib/chata-worker/.ssh/id_ed25519` na maszynie workera (właściciel `chata-worker`, tryb `0600`). Dodaj jego klucz publiczny do `/var/lib/chata-worker/.ssh/authorized_keys` na `lobster-dev01` (tryb `0600`). Zweryfikuj odcisk hosta przed dodaniem go do `known_hosts`. Kluczy nie dodawaj do repozytorium.
4. Sprawdź `sudo -u chata-worker ssh -o BatchMode=yes chata-worker@lobster-dev01 true`, następnie `sudo systemctl start chata-worker.service` i `journalctl -u chata-worker.service -n 100 --no-pager`.

Timer `chata-worker.timer` uruchamia wyszukiwanie co 2 godziny z losowym opóźnieniem do 5 minut. Pierwszy opublikowany manifest jest pobierany z serwera, więc przeniesienie workera na inną maszynę nie powoduje utraty wcześniejszych identyfikatorów ofert. Obrazy trafiają na serwer przed manifestem; ostatni krok to atomowa zmiana nazwy `manifest.json.part` na `manifest.json`.

Klucz CloakBrowser, jeśli jest potrzebny, ustaw w prywatnym systemd drop-in jako `CLOAKBROWSER_LICENSE_KEY`. Bez niego używana jest darmowa wersja przeglądarki.

## Aplikacja i proxy

W Coolify (`http://coolify:8000`) utwórz aplikację Docker Compose z repozytorium i plikiem `compose.yaml` na serwerze `lobster-dev01`. Kontener słucha na porcie 8080; port hosta `100.78.0.117:8088` jest związany wyłącznie z adresem Tailscale. Katalog `/srv/chata-data` jest montowany tylko do odczytu jako `/usr/share/nginx/html/runtime`. Caddy na `lobster-dev01` pozostaje na 80/443.

Na serwerze `coolify` dodaj plik dynamicznej konfiguracji Traefik na podstawie `deploy/chata-traefik.example.yaml`. W `/data/coolify/proxy/dynamic/chata-users` umieść hash `htpasswd` dla użytkownika `chata`, a następnie skonfiguruj trasę `chata.kveik.pl` z HTTP Basic i certyfikatem wildcard. Hasło i hash nie są częścią repozytorium. DNS wildcard pozostaje bez zmian.

## Sprawdzenie

`python -m unittest discover -s worker -v` sprawdza kryteria, identyfikatory portali, zachowanie ręcznych danych przy dwóch przebiegach i kolejność publikacji. Po instalacji workera sprawdź dwa kolejne uruchomienia timera, statusy sześciu źródeł w `manifest.json`, galerie oraz czas ostatniego przebiegu na stronie. Po ponownym wdrożeniu aplikacji sprawdź, że pliki w `/srv/chata-data/images` nadal są dostępne.
