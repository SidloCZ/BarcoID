# AGENTS.md – Pravidla projektu a instrukce pro AI asistenta

Tento soubor slouží jako centrální a závazná sada instrukcí pro AI asistenta v prostředí IDE (Antigravity, Cursor, Windsurf, VS Code, Gemini) pro projekt **BarcoID**.

---

# ČÁST I: PRAVIDLA TOHOTO PROJEKTU (Project-Specific)

## 1. Specifikace a technologický stack
- **Název projektu / repozitáře:** BarcoID (`barcoid`, CLI: `barcoid`, alias: `barco-id`)
- **Hlavní účel:** Multi-source validátor a křížový identifikátor DNA čárových kódů (DNA barcodes – COI, rbcL, 16S, ITS). Automaticky porovnává sekvence proti 4 nezávislým zdrojům důkazů (morfologická očekávání/defline metadat, BOLD Systems v5 REST API, NCBI GenBank QBLAST/local blastn a GBIF Taxonomic Backbone), stanovuje matici konkordance (`CONCORDANT`, `NEW_ASSIGNMENT`, `MISMATCH_ALERT`, `NO_MATCH`) a provádí QC detekci kontaminací (lidská DNA, neshody taxonů, falešné signály).
- **Tech stack:**
  - Python 3.9+ (podpora Python 3.9–3.12)
  - Standardní balíčkování: `pyproject.toml` (PEP 517 / PEP 621, Hatchling / Setuptools)
  - Knihovny: `biopython` (SeqIO, Bio.Blast), `requests`, `openpyxl` (stylizovaný multi-tab Excel), `urllib3`
  - Rozhraní a terminál: `rich` (živé progress bary, tabulky a barevný výstup), `argparse`
  - Volitelně: `pandas` (tabular/parquet exporty)
  - Testování a kvalita kódu: `pytest`, `pytest-mock`, `ruff`
- **Spouštěcí a testovací příkazy:**
  - Spuštění prototypu: `python multi_source_barcode_identifier.py --input <barcodes.fasta>`
  - Spuštění CLI modulu: `python -m barcoid.cli --input <barcodes.fasta>`
  - Spuštění nainstalovaného CLI: `barcoid --input <barcodes.fasta>`
  - Spuštění testů: `pytest` nebo `python -m pytest tests/`
  - Linter a statická kontrola: `ruff check .`
  - Automatické formátování kódu: `ruff format .`
  - Build distribučního balíčku: `python -m build`

## 2. Architektura a specifické konvence projektu
- **Klíčové složky a soubory:**
  - `src/barcoid/`: Zdrojový kód Python balíčku:
    - `cli.py`: Hlavní CLI rozhraní a zpracování argumentů.
    - `config.py`: Výchozí prahové hodnoty identity, limity API a konfigurace taxonů.
    - `cache.py`: SHA-256 perzistentní disková mezipaměť dotazů (`.id_cache/`).
    - `parsers/`: Parsery FASTA sekvencí (`fasta.py`), flexibilní regex parsery defline (`headers.py`), extraktor ONTbarcoder statistik (`ontbarcoder.py`) a externích tabulkových metadat (`metadata.py`).
    - `engines/`: Moduly pro komunikaci s externími autoritami – BOLD v5 REST API (`bold.py`), robustní NCBI QBLAST klient s ochranou proti zamrznutí (`blast_remote.py`), lokální blastn wrapper (`blast_local.py`) a GBIF Taxonomic Backbone match (`gbif.py`).
    - `arbitration/`: Logika pro vyhodnocení konsensu 4 zdrojů (`concordance.py`) a detekci kontaminací a anomálií (`qc.py`).
    - `exporters/`: Výstupní moduly – stylizovaný multi-tab sešit Excel (`excel.py`), tabulkové formáty TSV/CSV (`tabular.py`) a Markdown auditní report (`report.py`).
  - `tests/`: Jednotkové a integrační testy včetně offline mock odpovědí API (`tests/mocks/`).
  - `docs/`: Dokumentace, metodika a návody k použití.
  - `examples/`: Ukázkové testovací FASTA soubory a vzorová metadata.
  - `PLAN.md`: Kompletní specifikace architektury a roadmapa vývoje.
  - `0_Session_Context_and_Investigation_History.md`: Kontext a empirická zjištění z výchozího projektu BerlinBarcoding.
  - `multi_source_barcode_identifier.py`: Výchozí funkční skript (před refaktoringem do balíčku).
- **Specifická pravidla pro data, stav a API:**
  - **Perzistentní disková mezipaměť (`.id_cache/`):** Všechny výsledky volání externích API (BOLD, NCBI, GBIF) musí být deterministicky hashovány (SHA-256 ze sekvence a parametrů dotazu) a ukládány do lokální mezipaměti. Nikdy neopakovat stejný externí dotaz do sítě.
  - **NCBI QBLAST odolnost a limity:**
    - Vždy dodržovat per-request timeout (120–150 sekund) a automaticky rušit uvíznuté požadavky (stalled RID).
    - Vynucovat parametr `MEGABLAST: 'on'` pro nukleotidový DNA barcoding (akcelerace z minut na sekundy).
    - Adaptivní dávkování: Výchozí dávka maximálně 5 sekvencí na jeden QBLAST požadavek.
    - Sanitizace defline: Striktně odstraňovat prefixy `TPA_asm:`, `UNVERIFIED:`, `PREDICTED:` a další nestandardní tokeny před extrakcí binomického jména.
  - **Ochrana API klíčů a soukromí:** Nikdy neukládat do kódu ani do gitu osobní API klíče, e-maily či tokeny. Využívat proměnné prostředí (`NCBI_API_KEY`, `NCBI_EMAIL`) nebo CLI argumenty.
- **Větvení a verzování:**
  - Výchozí větev repozitáře je `main`.
  - Větev `dev` slouží pro vývoj a přípravu nových verzí.
  - Sémantické verzování (SemVer): Výchozí vývojová verze `0.1.0-dev`, první release `0.1.0`.
  - Před začleněním do větve `main` musí projít `pytest` a `ruff check .`.
- **Přístup k souborům:**
  - Před pokusem o přístup mimo složku tohoto workspace se vždy zeptej uživatele. Je nutné zamezit nepovoleným přístupům na jiné disky či k souborům mimo tento workspace.

---

# ČÁST II: UNIVERZÁLNÍ GLOBÁLNÍ STANDARDY (Global Core)

## 1. Komunikace, minimalismus a kontrola nad změnami

- **Méně je někdy více:**
  - Preferuj jednoduchá, čistá, funkční a věcná řešení.
  - Vyvaruj se překombinovaných návrhů a zbytečného kódu navíc.
- **Audit a transparentnost nepožádaných změn kódu:**
  - Pokud v kódu provedeš jakoukoliv změnu, refaktoring nebo optimalizaci, **o kterou uživatel v zadání výslovně nežádal**, VŽDY tuto změnu v odpovědi zřetelně zdůrazni a vysvětli její důvod.
  - Nápady a návrhy nad rámec původního zadání neimplementuj svévolně – popiš je v chatu jako dotaz či doporučení.
- **Striktní zákaz emoji:**
  - V celém projektu (uživatelské rozhraní, dialogy, toast zprávy, kód, komentáře, commit zprávy, texty i odpovědi asistenta) je **přísně zakázáno používat emoji**.
  - Místo emotikonů používej výhradně **pěkné, minimalistické, jednobarevné inline SVG**.
  - Zákaz Unicode vlaječek států (na Windows se vykreslují jako textová písmena) – vždy nahradit inline SVG vlajkou.
- **Faktická přesnost bez domýšlení:**
  - Nikdy si nevymýšlej neověřené parametry, čísla nebo fakta. Pokud chybí přesný zdroj či data, zeptej se uživatele nebo nastav prvek do stavu konceptu.

---

## 2. Nástroje IDE, Git a verzování

- **Nativní IDE nástroje:**
  - K vyhledávání, čtení a inspekci souborů používej nativní workspace nástroje (file search, read_file, grep).
  - Nepoužívej terminálové zkratky typu `node -e` ani ad-hoc bash skripty pro inspekci souborů.
- **Commit message (Conventional Commits):**
  - Na konci každé zprávy v chatu připrav výstižný návrh commit zprávy v angličtině podle konvence (`feat(...)`, `fix(...)`, `chore(...)`, `docs(...)`, `refactor(...)`, `style(...)`).
  - Vypiš **pouze čistý text zprávy** bez balení do `git commit -m` a bez uvozovek.
  - Asistent **nikdy nespouští commit ani push automaticky**, pouze navrhne zprávu a čeká na potvrzení uživatelem.
- **Sémantické verzování (SemVer) a Release Notes:**
  - Při aktualizaci verzí (`pyproject.toml`, `src/barcoid/__init__.py`) dodržuj:
    - **PATCH (`x.y.Z+1`):** Opravy chyb, drobný refaktoring, styly, textové úpravy.
    - **MINOR (`x.Y+1.0`):** Nové funkce, nové UI komponenty, rozšíření API.
    - **MAJOR (`X+1.0.0`):** Zlomové změny architektury, nekompatibilní přepracování.
  - **Automatické generování Release Notes:**
    - Při každé přípravě nového vydání (vytvoření nového git tagu, sestavení binárek nebo publikaci release na GitHubu) asistent **VŽDY automaticky sestaví kompletní anglické Release Notes** (přehled klíčových novinek a opravených chyb, odkazy na samostatné spustitelné soubory Windows/macOS/Linux a srozumitelné instrukce pro Windows SmartScreen „More info -> Run anyway“).
    - Tyto poznámky asistent uloží do `RELEASE_NOTES.md` a nabídne je uživateli přímo do chatu pro snadné vložení do GitHub Releases.
- **Udržování dokumentace:**
  - Při zásadní změně struktury kódu nebo novém prvku adekvátně aktualizuj soubory dokumentace (`README.md`, `STRUKTURA_PROJEKTU.md`, `RELEASE_NOTES.md`).

---

## 3. UI, UX a frontendový design

- **Jednoduchost UI prvků:**
  - Tlačítka, položky navigace a nadpisy formuluj stručně a výstižně (ideálně 1–2 slova).
  - Do UI nepřidávej svévolné dekorativní štítky a odznaky (badges jako „Novinka“, „Báze znalostí“), pokud nebyly vyžádány.
- **Parita světlého a tmavého režimu (Dark / Light mode):**
  - Při jakékoliv úpravě barev nebo motivů zajisti adekvátní kontrast a funkčnost v obou režimech současně.
- **Staging a produkční synchronizace:**
  - Pokud projekt využívá trvalé testovací či staging stránky (`temp-*`), udržuj jejich kód v synchronizovaném stavu s odpovídajícími ostrými verzemi.

---

## 4. Jazyková pravidla a česká mikrotypografie

- **Výchozí jazyk:** Řiď se jazykem promptu (typicky čeština; u webových projektů s `/en/` verzí udržuj překladovou paritu).
- **Zásady české mikrotypografie:**
  - **Pevné mezery (`&nbsp;` / `\u00A0`):** Neslabičné a jednopísmenné předložky a spojky (*k, s, v, z, o, u, a, i*) nesmí zůstávat na konci řádku. Vždy je navaž pevnou mezerou k následujícímu slovu.
  - **České uvozovky:** V českých textech používej výhradně uvozovky 99–66: dole `„` (U+201E) a nahoře `“` (U+201C). Zákaz rovných `""` i anglických `“...”`.
  - **Pomlčka vs. spojovník:**
    - Půlčtverčíková pomlčka (`–`, en-dash): Pro číselné rozsahy bez mezer (*10–15 mm*, *20–25 °C*) a jako větná pomlčka oddělená mezerami po obou stranách.
    - Spojovník (`-`, hyphen): Pouze pro těsně vázaná složená slova (*česko-slovenský*) nebo dělení slov.
  - **Jednotky a procenta:** Mezi číslem a jednotkou je vždy pevná mezera (`12&nbsp;mm`, `24&nbsp;°C`). U procent: `10 %` = deset procent (podstatné jméno), `10%` = desetiprocentní (přídavné jméno).
  - **Desetinná čísla a řády:** V českém textu piš desetinnou čárku (*1,5 mm*), v anglickém tečku (*1.5 mm*). Tisíce a vyšší řády odděluj mezerou (*10 000*).
- **Japonský jazyk (pokud je v projektu použit):**
  - Přepis do latinky uváděj vždy **českým přepisem** (vhodně doplněný o Hepburn). U kandži vždy doplň přepis do kany.

---

# ČÁST III: SPECIALIZOVANÝ MODUL – BIOLOGIE A MYRMEKOLOGIE
<!-- Tento modul je aktivní při tvorbě biologického, taxonomického a chovatelského obsahu -->

## 1. Binomická nomenklatura (Vědecké názvosloví)
- **Rod (Genus):** První písmeno velké, formátováno kurzívou (*Camponotus*, *Odontomachus*, *Lasius*, *Formica*).
- **Druhový přívlastek:** Všechna písmena malá, formátováno kurzívou (*ligniperda*, *tyrannicus*, *niger*).
- **Skupina druhů (Species group):** Pouze druhové jméno kurzívou, slovo „group“ nebo „skupina druhů“ normálním písmem bez kurzívy (*tyrannicus* group, skupina druhů *rufa*).
- **Vyšší taxony (Tribus, Podčeleď, Čeleď):** Velké počáteční písmeno, **normální písmo bez kurzívy** (Camponotini, Formicinae, Formicidae).
- **Zákaz CSS capitalize:** Nikdy nepoužívat CSS vlastnost `capitalize` ani automatické kapitálky na druhy (nepřípustné: *Camponotus Ligniperda*).

## 2. Odborná terminologie a překlady
- **Zákaz překládání molekulárních a genetických termínů:** Termíny jako *COI*, *DNA barcoding*, *Barcoding*, *Barcodes*, *PCR*, *mtDNA* apod. se **NIKDY NEPŘEKLÁDAJÍ** do češtiny (např. nepoužívat výrazy „čárové kódy DNA“). Ponechat standardní vědecké označení.
- **Přesná myrmekologická morfologie:**
  - Upřednostňuj exaktní terminologii (*gaster*, *petiolus*, *trofalaxe*, *nanitik*, *pleometróza*, *gamergát*, *ergatoid*).
  - Nepřidávat české názvy do závorek za odborné termíny, které se běžně nepřekládají.
  - **Diapauza:** Mravenci mají diapauzu; nepoužívat paušálně termíny „hibernace“ či „zimování“, pokud to není přesně fyziologicky podloženo.
  - **Subkasty a kasty:** Major je subkasta dělnice, voják (soldier) je samostatná kasta s unikátními morfologickými znaky (fragmotická hlava, šavlovitá kusadla). Množné číslo: majoři, minoři, medie (nikoliv „majory“, „minora“).