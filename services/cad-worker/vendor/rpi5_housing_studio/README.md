# Housing Studio - generator obudowy 2D/3D

Housing Studio jest gotowym projektem Python do parametrycznego generowania dwuczęściowej obudowy Raspberry Pi 5. Z jednej zwalidowanej konfiguracji tworzy:

- bryły 3D podstawy i klapy,
- STEP, STL, OBJ oraz GLB,
- rysunki 2D każdej części i całego złożenia,
- osobne widoki front, top i side w SVG,
- wielowarstwowe pliki DXF,
- dokumentację PDF,
- pliki JSON konfiguracji, warstw, metryk i ostrzeżeń,
- kompletną paczkę ZIP,
- lokalny interfejs webowy z podglądem 3D, podglądem 2D i pobieraniem plików.

LiteLLM jest używany jako bezpieczny „kompilator konfiguracji”: opis po polsku lub angielsku jest przekształcany w kompletny obiekt `ProjectConfig`, a następnie walidowany przez Pydantic. Model językowy nie generuje ani nie wykonuje kodu CAD.

## Najważniejsze elementy projektu

```text
rpi5_housing_studio/
├── generator.py                  # CLI oraz uruchamianie serwera
├── housing_studio/
│   ├── models.py                 # schemat całej konfiguracji
│   ├── llm_config.py             # LiteLLM + parser awaryjny
│   ├── cad3d.py                  # parametryczny model CadQuery
│   ├── draw2d.py                 # DXF/SVG/PDF i warstwy 2D
│   ├── artifacts.py              # orkiestracja i ZIP
│   ├── mesh_preview.py           # OBJ/GLB i wariant otwarty
│   └── validation.py             # metryki i sprzeczności wymiarowe
├── app/
│   ├── main.py                   # FastAPI
│   ├── templates/index.html      # interfejs webowy
│   └── static/                   # JavaScript i CSS
├── examples/
│   ├── rpi5_enclosure.json
│   ├── change_request_pl.txt
│   └── change_request_en.txt
├── docs/                           # specyfikacja, architektura i raport weryfikacji
├── tests/
├── Dockerfile
└── docker-compose.yml
```

## Wymagania

Zalecany jest Python 3.11, 3.12 lub 3.13. CadQuery 2.8 jest głównym silnikiem bryłowym, ezdxf odpowiada za dokumentację warstwową, a FastAPI obsługuje aplikację webową.

## Uruchomienie lokalne

```bash
cd rpi5_housing_studio
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e .
# Opcjonalnie pełna interpretacja przez LiteLLM:
python -m pip install -e ".[llm]"
python generator.py --serve
```

Następnie otwórz:

```text
http://127.0.0.1:8000
```

Dokumentacja API jest dostępna pod:

```text
http://127.0.0.1:8000/docs
```

Podgląd 3D w przeglądarce ładuje moduły Three.js z jsDelivr. Generowanie CAD, rysunków i paczek działa po stronie Pythona; dostęp do internetu jest potrzebny tylko do załadowania biblioteki podglądu w przeglądarce oraz do wywołania zewnętrznego modelu przez LiteLLM.

## Uruchomienie przez Docker

```bash
cp .env.example .env
mkdir -p generated
docker compose up --build
```

## Generowanie z pliku konfiguracyjnego

```bash
python generator.py \
  --config examples/rpi5_enclosure.json \
  --out generated \
  --job-id demo
```

## Generowanie z opisu naturalnego

```bash
python generator.py \
  --config examples/rpi5_enclosure.json \
  --prompt-file examples/change_request_pl.txt \
  --out generated
```

Bez zainstalowanego dodatku `llm` lub bez `LITELLM_MODEL` działa ostrożny parser lokalny. Rozpoznaje typowe polecenia dotyczące wymiarów, kąta otwarcia i włączania lub wyłączania warstw. Nie zgaduje pozostałych parametrów.

## Konfiguracja LiteLLM

Skopiuj plik środowiskowy:

```bash
cp .env.example .env
```

Ustaw model i klucz właściwego dostawcy:

```dotenv
LITELLM_MODEL=openai/your-model-name
OPENAI_API_KEY=...
```

Można użyć innego dostawcy wspieranego przez LiteLLM albo własnego serwera zgodnego z OpenAI:

```dotenv
LITELLM_MODEL=your-provider/your-model
LITELLM_API_BASE=http://localhost:4000
LITELLM_API_KEY=...
```

Proces interpretacji wygląda następująco:

1. Do modelu trafia bieżąca pełna konfiguracja oraz opis zmian.
2. LiteLLM próbuje wymusić wynik zgodny z JSON Schema `ProjectConfig`.
3. Gdy dostawca nie obsługuje ścisłego schematu, wykonywana jest próba w trybie JSON object.
4. Wynik jest ponownie walidowany przez Pydantic.
5. Dopiero zwalidowana konfiguracja trafia do CadQuery i generatora dokumentacji.
6. Przy błędzie wywołania używany jest lokalny parser awaryjny.

Klucze API pozostają wyłącznie po stronie serwera. Interfejs przeglądarkowy ich nie odczytuje ani nie przesyła.

## Warstwy projektu

Projekt rozróżnia dwa rodzaje warstw.

### Warstwy funkcjonalne 3D

- `base_shell`
- `lid_shell`
- `hinge`
- `pcb_mount_a`
- `pcb_mount_b`
- `camera_mounts`
- `lid_aux_bosses`
- `rear_tabs`
- `connector_openings`
- `locating_lip`
- `pcb_reference`

Każdą warstwę można włączyć albo wyłączyć w JSON lub opisem naturalnym.

### Warstwy rysunku 2D

- `VISIBLE_EDGES`
- `HIDDEN_EDGES`
- `CENTERLINES`
- `DIMENSIONS`
- `NOTES`
- `SECTION_HATCH`
- `PCB_REFERENCE`
- `CONSTRUCTION`
- `DATUMS`

Nazwa DXF, typ linii, szerokość oraz indeks koloru są częścią konfiguracji.

## Domyślna geometria

Konfiguracja przykładowa uwzględnia między innymi:

- szerokość zewnętrzną 79 mm,
- głębokość zewnętrzną 95 mm jako **założenie robocze** wynikające z 80 mm płaskiego dachu oraz odsunięć 13 mm i 2 mm,
- wysokość całkowitą 40 mm,
- wysokość podstawy 25 mm,
- ściany, dno i dach o grubości 2 mm,
- płaski fragment dachu o głębokości 80 mm,
- końcowe 2 mm ścian klapy w pionie,
- przednią powierzchnię klapy pod kątem 45°,
- zawias z trzema segmentami podstawy i dwoma segmentami klapy oraz domyślnym luzem średnicowym 0,2 mm dla sworznia,
- kąt podglądu otwarcia 195°,
- dwa zestawy czterech słupków montażowych Raspberry Pi,
- sześć punktów kamery oraz cztery dodatkowe punkty w klapie,
- otwór złącza jako konfigurowalną warstwę z opcjonalnym promieniem naroży,
- nominalne promienie krawędzi oraz luz otworu zawiasu sterowane konfiguracją.

## Założenia wymagające potwierdzenia

Źródła podają 80 mm dla płaskiego fragmentu górnej powierzchni, ale nie podają niezależnego wymiaru całkowitej głębokości obudowy. Domyślne 95 mm jest więc jawnym założeniem roboczym: 13 mm skosu z przodu + 80 mm części płaskiej + 2 mm z tyłu. Położenia otworów złączy również należy zweryfikować na finalnym zespole PCB i wtykach. Generator pokazuje te kwestie jako ostrzeżenia informacyjne.

## Istotna sprzeczność źródłowa

Dla pozycji montażowej B podano jednocześnie:

- 7,5 mm od wewnętrznej prawej ściany,
- 10,5 mm od wewnętrznej lewej ściany,
- PCB o szerokości 56 mm,
- obudowę o szerokości zewnętrznej 79 mm i ścianach 2 mm.

Daje to 74 mm po stronie wymagań i 75 mm dostępnej szerokości wewnętrznej. Generator zachowuje prawą odległość 7,5 mm jako punkt kotwiczenia, wylicza 11,5 mm po lewej i zgłasza ostrzeżenie. Wartość nie jest automatycznie uśredniana ani ukrywana.

## Struktura wygenerowanego zadania

```text
generated/<job-id>/
├── project_config.json
├── project_config.schema.json
├── project_layers.json
├── design_metrics.json
├── design_warnings.json
├── technical_specification.md
├── manifest.json
├── 3d/
│   ├── base.step
│   ├── base.stl
│   ├── base.obj
│   ├── lid.step
│   ├── lid.stl
│   ├── lid.obj
│   ├── assembly.step
│   ├── assembly.glb
│   ├── assembly_open.glb
│   └── model_stats.json
├── 2d/
│   ├── base/
│   ├── lid/
│   └── assembly/
└── housing_project_bundle.zip
```

## API

Najważniejsze endpointy:

```text
GET  /api/default-config
POST /api/interpret
POST /api/generate
GET  /api/jobs/{job_id}
GET  /health
```

Przykład interpretacji:

```bash
curl -X POST http://127.0.0.1:8000/api/interpret \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "prompt": "Ustaw grubość ścian na 2.4 mm i wyłącz drugi wariant PCB",
  "config": null
}
JSON
```

## Testy

```bash
pytest
```

Testy sprawdzają schemat, parser lokalny, most LiteLLM z odpowiedzią zgodną z JSON Schema, bryły CadQuery, szczelność siatek STL, warstwy DXF, kompletność paczki oraz podstawowe endpointy FastAPI. Szczegóły znajdują się w `docs/VERIFICATION.md`.

## Ograniczenia inżynierskie

Generator jest parametrycznym punktem wyjścia, a nie zamiennikiem prototypowania. Szczególnie należy sprawdzić:

- kolizje klapy podczas pełnego obrotu,
- średnicę i metodę montażu sworznia,
- luz zawiasu po konkretnym wydruku FDM,
- rzeczywisty model komponentów na spodzie płytki,
- wszystkie wtyki i promienie gięcia przewodów,
- odporność słupków na wkręty,
- wpływ kierunku druku na jakość powierzchni,
- wentylację i temperaturę Raspberry Pi 5.

Pliki STEP są prawidłowymi bryłami B-Rep wygenerowanymi bezpośrednio z modelu CadQuery. Nie zawierają jednak historii operacji SolidWorks; rolę natywnego, edytowalnego źródła pełni konfiguracja JSON oraz kod Python generatora.
