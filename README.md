# OfficeCraft

Hub z narzędziami open source (PDF, CAD, modelowanie 3D), które działają **w przeglądarce** -
kompilowane do WebAssembly przez ich autorów. Strona pobiera najnowsze wydania z GitHuba
i sama je wdraża.

- Strona główna: lista narzędzi (przycisk → podstrona z narzędziem)
- Podstrona narzędzia: pasek (wersja, nowa karta, pełny ekran) + aplikacja w `iframe`
- Ukryta strona `/admin/`: stan wersji + ręczne uruchomienie aktualizacji
- Codzienna automatyczna synchronizacja (GitHub Actions, cron)

Koszt: **0 zł**. Całość działa na GitHubie - GitHub Pages (strona) + GitHub Actions (pobieranie
i wdrażanie buildów). Żadnych sekretów w repozytorium, żadnych serwerów.

---

## 1. Dodanie narzędzia

Otwórz `tools.txt` i dopisz **akapit** - link do repozytorium, a pod nim opcjonalnie opis:

```
https://github.com/storytold/pdfcraft
Czytaj, porządkuj, łącz i zabezpieczaj pliki PDF - w przeglądarce.

https://github.com/storytold/cadcraft
Rysowanie 2D i 3D w stylu AutoCADa: warstwy, wymiary, kresowanie, DXF - w przeglądarce.

https://github.com/tangency-labs/solidcraft
Parametryczne modelowanie 3D w stylu SolidWorksa - w przeglądarce.
```

Akapity rozdziela pusta linia. Opis może być zapisany wieloma wierszami - zostaną sklejone
spacją. Jeśli opisu nie podasz, hub pokaże opis z repozytorium.

To wszystko. Przy najbliższej synchronizacji skrypt sam:

- sprawdzi najnowsze **wydanie stabilne** (prerelease/nightly są pomijane),
- znajdzie w nim asset `<nazwa-repo>-web-<wersja>.zip`,
- go pobierze, rozpakuje i wgra na stronę,
- doda kartę na hubie i podstronę `/tool/<nazwa-repo>/`,
- dobierze nazwę, ikonę i link do projektu.

Jeśli dane repozytorium nie ma buildu webowego, narzędzie pokaże się na hubie jako
przygaszona karta „brak wersji webowej”, a w `/admin/` jako „pominięte” - reszta synchronizacji
przebiega normalnie.

Opcjonalne ustawienia (po `|`, nie trzeba używać):

```
https://github.com/storytold/xyz | label=XYZ | page=https://… | icon=https://… | asset=xyz-web-{v}.zip
```

| Pole | Znaczenie |
|---|---|
| `id` | identyfikator w adresach (domyślnie nazwa repozytorium) |
| `label` | nazwa na stronie |
| `page` | link do strony projektu |
| `icon` | własna ikona (URL) |
| `asset` | wzorzec nazwy pliku; `{v}` = wersja, `{id}` = identyfikator |
| `repo` | jawne `owner/repo`, gdy link nie jest adresem GitHuba |

---

## 2. Jak to działa

```
tools.txt ──► scripts/sync_tools.py ──► site-out/apps/<id>/   (rozpakowane buildy)
                          │             site-out/manifest.json (wersje)
                          │             site-out/.deploy-needed  ( czy jest co wdrażać )
                          ▼
                scripts/build_site.py ──► site-out/index.html, /tool/<id>/, /admin/
                          │
                          ▼
              actions/upload-pages-artifact ──► actions/deploy-pages ──► GitHub Pages
```

Przebieg `sync_tools.py`:

1. pyta API GitHuba o najnowsze wydanie każdego narzędzia,
2. porównuje wersję z wdrożoną (manifest z żywej strony albo plik `--state`),
3. **pobiera tylko narzędzia, których wersja się zmieniła**,
4. rozpakowuje ZIP (z pominięciem górnego folderu) do `site-out/apps/<id>/`,
5. zapisuje `manifest.json`.

Jeśli żadne narzędzia się nie zmieniły, skrypt nie pobiera nic i nie wgrywa nic -
przebieg kończy się komunikatem `DEPLOY: niepotrzebny - bez zmian`, a akcja pomija wdrożenie.

Wymuszenie ponownego pobrania (np. gdyby plik się uszkodził): akcja → **Run workflow** →
zaznacz `force`.

### Instalacja jako aplikacja (PWA) i otwieranie plików

Każdy build w `apps/<id>/` dostaje przy każdym wdrożeniu `manifest.webmanifest` (nazwa, ikony
192/512, `display: standalone`) oraz `file_handlers` - listę rozszerzeń, które dana aplikacja
obsługuje. Dzięki temu po zainstalowaniu w Edge/Chrome ("Zainstaluj aplikację") system
rejestruje ją jako program do tych plików i dwuklik otwiera je w aplikacji.

Dopisywanie odbywa się w `scripts/build_site.py` (funkcja `prepare_apps`), więc po każdej
nowej wersji rozpakowanej z ZIP-a manifest i skrypt są tworzone od nowa. Rozszerzenia są
zdefiniowane w `scripts/pwa.py` (`FILE_TYPES`); własny manifest narzędzia (np. SolidCraft)
jest zachowywany, a tylko uzupełniany.

Plik z systemu trafia do aplikacji przez File Handling API (`launchQueue`); dołączany
`officecraft-pwa.js` podaje go aplikacji jako przeciągnięcie pliku na kanwę.

Ten sam skrypt obsługuje przycisk **„Zainstaluj jako aplikację"** na stronie narzędzia:
otwiera on `apps/<id>/?install=1`, gdzie pojawia się panel z przyciskiem wywołującym
systemowy dialog instalacji (PWA instaluje się tylko ze strony najwyższego poziomu,
nie z iframe podglądu).

---

## 3. Wdrożenie (jednorazowo)

1. Utwórz **publiczne** repozytorium `OfficeCraft` na GitHubie.
   Publiczne jest konieczne: GitHub Pages w prywatnym repozytorium wymaga planu Pro.
2. Wypchnij pliki na gałąź `main`.
3. W repozytorium: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
   Przy pierwszym uruchomieniu kliknij w podpowiedzi **Configure Pages → GitHub Actions**.
4. Wypchnij zmiany na `main` - workflow uruchomi się sam przy zmianie `site/`,
   `scripts/`, `tools.txt` lub samego workflow. Pierwszy przebieg pobierze ~45 MB
   i wgra ~115 MB na Pages; trwa 3–5 minut. Kolejne korzystają z cache buildów.

Adres strony: `https://<twoj-nick>.github.io/<nazwa-repo>/` (przy repo `OfficeCraft`:
`https://<twoj-nick>.github.io/OfficeCraft/`).

Strona `/admin/` nie jest nigdzie linkowana i jest wykluczona z indeksowania
(`robots.txt` + `noindex`).

### Fork - własna kopia na Twoim koncie

1. Na GitHubie otwórz repozytorium i kliknij **Fork → Create fork**. Nazwa może zostać
   `OfficeCraft` (najprościej) - inna też zadziała, bo adresy stron i akcji są liczone
   z repozytorium, w którym działają.
2. W swoim forku wejdź w **Actions**. Jeśli pojawi się komunikat, że workflowy są wyłączone,
   kliknij **I understand my workflows, go ahead and enable them**.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. W **Actions → Sync tools** kliknij **Enable workflow**. W forku harmonogram (cron) jest
   domyślnie wyłączony - bez tego kroku codzienna synchronizacja nie ruszy (ręczne
   **Run workflow** działa od razu).
5. Wypchnij zmianę na `main` albo uruchom **Run workflow** - pierwszy przebieg pobierze
   buildy i wdroży stronę.

Ważne przy forku:

- Repozytorium musi być **publiczne** - GitHub Pages dla prywatnych wymaga planu Pro.
- Workflow zakłada gałąź `main`. Jeśli Twój fork ma inną, popraw `branches: [main]`
  i `GITHUB_REF_NAME` w `.github/workflows/sync-tools.yml`.
- Własna domena: ustaw zmienną repozytorium `SITE_URL` (**Settings → Secrets and variables →
  Actions → Variables**) na pełny adres, np. `https://office.example.com/`. Bez niej adres
  jest brany z `GITHUB_REPOSITORY`.
- Token z sekcji 4 twórz dla **swojego** forka (`Only select repositories` → Twoja kopia).
- Aby brać aktualizacje z oryginału:

  ```bash
  git remote add upstream https://github.com/costuwpisze/OfficeCraft.git
  git fetch upstream
  git merge upstream/main
  ```

---

## 4. Strona `/admin/` - ręczna aktualizacja

Dwa sposoby uruchomienia synchronizacji:

**A. Przez GitHub (bez tokenów)** - przycisk *Uruchom przez GitHub* otwiera
`github.com/<owner>/<nazwa-repo>/actions/workflows/sync-tools.yml`, gdzie logujesz się
normalnie do GitHuba i klikasz **Run workflow**.

**B. Tokenem (PAT)** - *Personal Access Token* to „hasło do API GitHuba": długi ciąg znaków,
który dowodzi, że to Ty, działa tylko na to, co mu dasz, ma datę ważności i można go
unieważnić w każdej chwiej. Tworzysz go w GitHub → **Settings → Developer settings →
Personal access tokens → Fine-grained tokens → Generate new token**:

- nazwa: `OfficeCraft`
- ważność: 90 dni (lub dłużej)
- **Resource owner:** Twoje konto
- **Repository access: Only select repositories → Twoja kopia** (np. `OfficeCraft`)
- **Repository permissions:**
  | Uprawnienie | Poziom | Po co |
  |---|---|---|
  | **Contents** | Read and write | `git push` (wypychanie plików) |
  | **Actions** | Read and write | uruchamianie i odczyt przebiegów workflow (`/admin/`) |
  | **Workflows** | Read and write | `git push` plików z `.github/workflows/` (Twój pierwszy commit zawiera workflow) |
- **Generate token** → skopiuj token (widoczny tylko raz)

Jeden token wystarczy na oba zastosowania. Uprawnienia **Pages** nie są potrzebne -
wdrażanie na strony robi sam workflow na automatycznym `GITHUB_TOKEN`.

Sprawdzenie tokenta:

```bash
curl -s -H "Authorization: Bearer TWOJ_TOKEN" https://api.github.com/repos/TWOJ-NICK/NAZWA-REPO | head -3
```

Przy `git push` po HTTPS: login = Twój nick, hasło = token (GitHub nie przyjmuje hasła konta).
Token możesz zapamiętać, żeby nie wklejać go za każdym razem:

```bash
git config --global credential.helper store    # zapisuje w ~/.git-credentials (tekstem!)
```

Alternatywa bez tokenu do pchania: **SSH** (`git remote add origin git@github.com:TWOJ-NICK/OfficeCraft.git`).

Token wklejasz w polu na stronie `/admin/`. Trzymany jest w `sessionStorage` (znika po
zamknięciu karty) i wysyłany **wyłącznie do `api.github.com** - nigdzie indziej.

Panel pokazuje też, dla każdego narzędzia, wersję wdrożoną i wersję najnowszą na GitHubie
(zielona „aktualne" / niebieska „nowa wersja"), więc widzisz, czy jest co aktualizować,
zanim cokolwiek uruchomisz.

---

## 5. Uruchomienie lokalnie (do testów)

```bash
python3 scripts/sync_tools.py --out site-out --dry-run   # tylko sprawdzenie wersji
python3 scripts/sync_tools.py --out site-out               # pobranie i rozpakowanie
python3 scripts/build_site.py --out site-out               # złożenie strony
python3 -m http.server 8000 --directory site-out          # podgląd na http://localhost:8000
```

Wymagania: Python 3.9+ (tylko biblioteka standardowa). Do testów z pobieraniem wystarczy
konto bez tokenu; limit API GitHuba to 60 zapytań na godzinę na adres IP.

---

## 6. Ograniczenia, o których warto wiedzieć

| | |
|---|---|
| Rozmiar strony | ~115 MB (trzy narzędzia) - limit GitHub Pages to 1 GB |
| Pasmo | miękki limit GitHuba: **100 GB miesięcznie**. Jedno uruchomienie SolidCraft to ~51 MB, więc ~2000 uruchomień miesięcznie |
| Typ MIME `.wasm` | GitHub Pages podaje `application/wasm`; gdyby podał inny, aplikacja i tak ruszy (wolniej, bez streamingu) - kod glue ma na to fallback |
| Cron Actions | uruchamia się z opóźnieniem do ~1 h; **wyłącza się po 60 dniach bez aktywności repozytorium** - dlatego jest `/admin/` |
| Cache buildów | `site-out/apps` (~120 MB) jest odtwarzany między przebiegami, więc codzienna synchronizacja pobiera tylko nowe wersje |
| Aktualizacja | trwa 3–5 min (pobranie + wgranie ~115 MB) |
| Service worker SolidCraft | wymaga, aby cały build leżał w jednym katalogu - dlatego buildy są w `/apps/<id>/`, nietknięte |

Licencje i pliki `NOTICE` autorów są zachowane w katalogach `/apps/<id>/`; buildy są
wdrażane w oryginalnej, niezmienionej postaci.

---

## 7. Struktura repozytorium

```
tools.txt                      lista narzędzi (linki + opisy)
site/                          szablony i style stron
  hub.template.html            strona główna
  tool.template.html           podstrona narzędzia
  admin.template.html          strona administracyjna
  assets/                      CSS i JS
scripts/
  common.py                    wspólne: parser konfiguracji, szablony, manifest
  sync_tools.py                sprawdzanie wersji, pobieranie, rozpakowywanie
  build_site.py                składanie witryny
  pwa.py                       manifest PWA + otwieranie plików z systemu
.github/workflows/
  sync-tools.yml               cron + ręczne uruchomienie + wdrożenie na Pages
```
