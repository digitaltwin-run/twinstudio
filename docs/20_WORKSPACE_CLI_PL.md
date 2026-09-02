# Projekty TwinStudio z CLI

Polecenia `twinstudio workspace` są klientem publicznego API
`/api/v1/workspaces`. Nie otwierają bezpośrednio `.projects` i nie omijają
autoryzacji, rejestracji projektu ani blokady zapisu. Viewer korzysta z tej
samej granicy HTTP.

## Konfiguracja

Lokalny serwer developerski:

```bash
export TWINSTUDIO_API_BASE=http://127.0.0.1:8500
twinstudio workspace list
```

Przy wyłączonym `DEV_AUTH_BYPASS` podaj konto i osobisty token HTTP Basic.
Token najlepiej przekazać zmienną środowiskową, aby nie trafiał do historii
powłoki:

```bash
export TWINSTUDIO_API_BASE=https://studio.example.com
export TWINSTUDIO_API_EMAIL=user@example.com
read -rsp 'TwinStudio token: ' TWINSTUDIO_API_TOKEN
export TWINSTUDIO_API_TOKEN
```

Każda komenda obsługuje także globalne opcje `--url`, `--email`, `--token` i
`--timeout`. Umieszcza się je przed nazwą operacji.

## Utworzenie i sprawdzenie projektu

```bash
twinstudio workspace create 'Mysz RP2040 Zero' \
  --project-id mysz-rp2040-zero --kind electronics

twinstudio workspace list
twinstudio workspace show mysz-rp2040-zero
twinstudio workspace plan mysz-rp2040-zero
```

Nowy projekt otrzymuje osobny katalog, manifest, standardowe podkatalogi,
`planfile.yaml` oraz licencję Apache-2.0.

## Dodawanie i pobieranie plików

```bash
twinstudio workspace upload mysz-rp2040-zero firmware/code.py \
  --path firmware/code.py

twinstudio workspace download mysz-rp2040-zero firmware/code.py \
  --out /tmp/mysz-code.py
```

Istniejącego pliku nie można nadpisać przypadkiem. Kontrolowana aktualizacja
zwykłego pliku wymaga aktualnego SHA-256:

```bash
SHA=$(twinstudio workspace show mysz-rp2040-zero \
  | jq -r '.files[] | select(.path == "docs/README.md") | .sha256')

twinstudio workspace upload mysz-rp2040-zero README.md \
  --path docs/README.md --overwrite --expected-sha256 "$SHA"
```

Plików `.kicad_sch` i `.kicad_pcb` nie aktualizuje się tą komendą. Źródła EDA
muszą przejść osobny proces `twinstudio eda`: plan, dry-run, kandydat, kontrole,
akceptacja i dopiero potem promocja.

## Przeniesienie na drugi komputer

Na komputerze źródłowym:

```bash
twinstudio workspace export mysz-rp2040-zero \
  --out mysz-rp2040-zero.zip
sha256sum mysz-rp2040-zero.zip
```

Przenieś ZIP dowolnym kanałem, a na komputerze docelowym wykonaj:

```bash
twinstudio workspace import mysz-rp2040-zero.zip \
  --name 'Mysz RP2040 Zero' --project-id mysz-rp2040-zero

twinstudio workspace show mysz-rp2040-zero \
  | jq '.project.content_fingerprint_sha256'
```

`content_fingerprint_sha256` powinien być taki sam na obu komputerach. Lokalny
identyfikator paczki może się różnić, dlatego do kontroli transferu używany jest
fingerprint treści, a nie pełny fingerprint manifestu.

## Klonowanie i kontrolowany merge

```bash
twinstudio workspace clone mysz-rp2040-zero 'Mysz — wariant B' \
  --project-id mysz-rp2040-zero-b

twinstudio workspace merge-plan mysz-rp2040-zero mysz-rp2040-zero-b \
  --strategy reject > merge-plan.json

PLAN_SHA=$(jq -r '.plan_sha256' merge-plan.json)
twinstudio workspace merge-apply mysz-rp2040-zero mysz-rp2040-zero-b \
  --strategy reject --plan-sha256 "$PLAN_SHA"
```

`merge-plan` jest tylko podglądem. `merge-apply` wymaga hasha dokładnie tego
planu; zmiana któregokolwiek projektu unieważnia plan i zapobiega zastosowaniu
nieaktualnej decyzji.

## Diagnostyka

```bash
twinstudio workspace --help
twinstudio workspace upload --help
curl -fsS "$TWINSTUDIO_API_BASE/health" | jq
```

Typowe kody:

- `PROJECT_EXISTS` — identyfikator jest już zajęty;
- `PROJECT_FILE_EXISTS` — upload próbował nadpisać istniejący plik;
- `PROJECT_FILE_CHANGED` — podany SHA-256 jest nieaktualny;
- `PROJECT_EDA_CANDIDATE_REQUIRED` — próba bezpośredniej zmiany źródła KiCad;
- `PROJECT_MERGE_STALE` — projekt zmienił się po wyliczeniu planu merge;
- `PROJECT_WRITE_DISABLED` — administrator uruchomił usługę read-only.

## Powtarzalny test end-to-end

Repozytorium zawiera test uruchamiający tymczasową instancję TwinStudio i
wykonujący przez CLI pełny przepływ create, upload, export, import, kontrolę
fingerprintu, dwuetapowy merge oraz download. Test potwierdza również, że
nadpisanie istniejącego źródła KiCad jest odrzucane:

```bash
make workspace-cli-e2e
```

Wynik wskazuje katalog `/tmp/twinstudio-workspace-cli.*` z odpowiedziami JSON,
logiem serwera, archiwum ZIP i końcowym `report.json`. Port oraz katalog dowodów
można ustawić przez `TWINSTUDIO_CLI_E2E_PORT` i `TWINSTUDIO_CLI_E2E_ROOT`.
