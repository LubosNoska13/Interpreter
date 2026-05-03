# SOL26 Interpreter

Projekt obsahuje interpret jazyka SOL26, integračný tester a technickú dokumentáciu
k riešeniu. Interpret načítava program v XML reprezentácii SOL-XML, vykoná statické
kontroly a spustí metódu `run` triedy `Main`.

## Štruktúra projektu

```text
.
├── int/              # Python interpret SOL26
│   ├── src/solint.py # vstupný bod interpretu
│   └── src/interpreter/
├── tester/           # TypeScript integračný tester
│   └── src/tester.ts
├── doc/              # LaTeX dokumentácia a UML diagram
└── Dockerfile        # stage pre kontroly, runtime aj tester
```

## Požiadavky

- Python 3.14
- Node.js 24.12 alebo novší, iba pre tester
- `diff`, iba pre porovnanie výstupov v integračnom testeri
- voliteľne Docker

## Interpret

Inštalácia závislostí:

```bash
cd int
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Spustenie interpretu:

```bash
python3 src/solint.py --source cesta/program.xml
```

Ak program potrebuje vstup, dá sa pridať súbor so štandardným vstupom:

```bash
python3 src/solint.py --source cesta/program.xml --input cesta/vstup.txt
```

Prepínač `-v` zapne informačné logovanie, `-vv` zapne debug logovanie.

### Návratové kódy interpretu

| Kód | Význam |
| --- | --- |
| 10 | chyba parametrov príkazového riadku |
| 11 | chyba pri otváraní vstupného súboru |
| 20 | nevalidné alebo neparsovateľné XML |
| 31 | chýba trieda `Main` alebo metóda `run` |
| 32 | použitie nedefinovaného symbolu |
| 33 | chyba arity |
| 34 | kolízia pri priradení do parametra bloku |
| 35 | iná statická sémantická chyba |
| 42 | neočakávaná štruktúra SOL-XML |
| 51 | objekt nerozumie správe |
| 52 | iná runtime chyba |
| 53 | neplatná hodnota argumentu |
| 54 | pokus o vytvorenie atribútu kolidujúceho s metódou |
| 99 | neočakávaná interná chyba |

## Integračný tester

Tester vyhľadáva súbory vo formáte SOLtest, spúšťa parser a/alebo interpret a
vypíše JSON report.

Inštalácia a build:

```bash
cd tester
npm ci
npm run build
```

Spustenie testov iba nad interpretom:

```bash
npm run start -- cesta/k/testom --interpreter "python3 ../int/src/solint.py"
```

Rekurzívne spustenie s výstupom do súboru:

```bash
npm run start -- cesta/k/testom -r -o report.json --interpreter "python3 ../int/src/solint.py"
```

Ak testy vyžadujú aj SOL2XML parser, pridaj parameter `--parser`:

```bash
npm run start -- cesta/k/testom \
  --parser "cesta/k/parseru" \
  --interpreter "python3 ../int/src/solint.py"
```

Užitočné prepínače testera:

- `--dry-run` iba nájde a naparsuje testy
- `-r`, `--recursive` prehľadáva aj podadresáre
- `-i`, `--include` zahrnie test podľa názvu alebo kategórie
- `-e`, `--exclude` vylúči test podľa názvu alebo kategórie
- `-ic`, `-it`, `-ec`, `-et` filtrujú explicitne kategórie alebo názvy testov
- `-g`, `--regex-filters` interpretuje filtre ako regulárne výrazy

## Vývojové kontroly

Python časť:

```bash
cd int
pip install -e . -r requirements-dev.txt
./ruff check src
./ruff format --check src
./mypy src
```

TypeScript časť:

```bash
cd tester
npm run typecheck
npm run lint
npm exec -- prettier --check "src/**/*.ts"
```

## Docker

Statické kontroly pre interpret aj tester:

```bash
docker build --target check -t sol26-check .
```

Runtime image interpretu:

```bash
docker build --target runtime -t sol26-interpreter .
docker run --rm -v "$PWD:/work" sol26-interpreter --source /work/int/test.xml
```

Image s testerom:

```bash
docker build --target test -t sol26-tester .
docker run --rm -v "$PWD:/work" sol26-tester /work/cesta/k/testom -r
```

## Dokumentácia

Dokumentácia je v adresári `doc/`. PDF sa dá vygenerovať príkazom:

```bash
cd doc
make
```

Výsledkom je `doc/doc.pdf`; UML diagram sa generuje z `doc/uml.dot`.
