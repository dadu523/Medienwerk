# Medienwerk lokal testen

## Starten

Die Abhängigkeiten wurden in diesem Arbeitsverzeichnis installiert. Zum Starten:

```bash
./start-local.sh
```

Danach http://localhost:3000 im Browser öffnen. Das Terminal geöffnet lassen.
Mit `Strg+C` werden Frontend und Backend beendet. Wenn die Anwendung bereits
läuft, ist kein weiterer Start notwendig.

Beide Server lauschen ausschließlich auf `127.0.0.1`. Das Backend ist unter
http://127.0.0.1:8008/health erreichbar. Die Oberfläche leitet `/api`-Anfragen
und WebSocket-Verbindungen an das lokale Backend weiter.

## Ohne API-Schlüssel ausprobieren

- Zwischen den Seiten navigieren.
- Unter **Settings & APIs** Einstellungen bearbeiten und speichern.
- Unter **Video Tools → Ratio Converter** ein kurzes eigenes Video hochladen und
  in das Hoch- oder Querformat umwandeln. Die Konvertierung verwendet FFmpeg und
  braucht keinen KI-Anbieter.
- Das Ergebnis abspielen oder herunterladen.

Für KI-Texte, Stimmen, Bilder oder Videos müssen die API-Schlüssel der gewählten
Anbieter unter **Settings & APIs** eingetragen werden. Aufrufe können beim
jeweiligen Anbieter kostenpflichtig sein. Schlüssel werden lokal in der von Git
ignorierten `config.json` gespeichert.

Die simulierten Social-Verbindungen des ursprünglichen Projekts sind deaktiviert.
TikTok/Instagram sind nicht verfügbar; der vorhandene YouTube-Upload benötigt
echte OAuth-Zugangsdaten und wurde in der lokalen Abnahme nicht veröffentlicht. Google VideoFX benötigt zusätzlich einen
installierten Chrome-Browser und eine interaktive Anmeldung.

## Installation in einem neuen Klon

Voraussetzungen: Python 3.11, Node.js 22 oder neuer und FFmpeg. Der lokale
Abhängigkeitsstand ist in `requirements-local.lock` festgehalten. Vom
Projektordner aus ausführen:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-local.lock
cd web
npm ci
cd ..
./start-local.sh
```

Die Lockdatei pinnt den am 11. Oktober 2026 installierten Python-Stand und
verweist für das CPU-Build von PyTorch auf `https://download.pytorch.org/whl/cpu`.
`npm ci` verwendet den vorhandenen `web/package-lock.json`. Whisper lädt das
benötigte Sprachmodell beim ersten Transkriptionslauf herunter.

Der erfasste lokale Stand ist Python 3.11.15, Torch 2.14.1+cpu, Node.js
26.11.1, npm 12.2.0 und FFmpeg 9.0.2. In der bestehenden virtuellen Umgebung
ist `pip` nicht installiert; die dokumentierte Neuinstallation legt eine neue
Umgebung mit pip an.

## Prüfungen ausführen

Die Backend-Tests verwenden temporäre Datenbank-, Workspace-, Konfigurations-
und Kampagnendateien. Provideraufrufe und Publishing werden in den Tests nicht
automatisch ausgelöst. Nach der Installation der Anwendungsabhängigkeiten die
Prüfwerkzeuge ergänzen:

```bash
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
```

`requirements-test.txt` hält pytest 9.1.1 sowie httpx2 2.13.1 und die kleinen
Testlaufzeitabhängigkeiten fest. httpx2 wird für den aktuellen FastAPI-/Starlette-
`TestClient`-Stack benötigt; die Anwendungsabhängigkeiten bleiben in der
separaten Python-Lockdatei.

Für eine separate Frontend-Prüfung (den Dev-Server vorher beenden oder eine
separate Kopie verwenden, da Build und Dev dieselbe `.next`-Ablage nutzen):

```bash
cd web
npm ci
npm run build
```

`npm run build` ersetzt keine Browserprüfung. Eine Browserabnahme und echte
Anbieterläufe sind separat zu planen; echte Anbieterläufe können kostenpflichtig
sein.

## Migration manuell zurücksetzen

Der Programmstart führt ausschließlich Vorwärtsmigrationen aus. Einen Rückweg
nicht auf der laufenden Anwendungsdatenbank ausführen. Zuerst die Datenbank mit
SQLite-Backup in eine separate Datei kopieren, Sicherung prüfen und dann gezielt
die Kopie verwenden. Beispiel für eine bewusst leere Testkopie:

```bash
MEDIENWERK_DATABASE_URL="sqlite:////absolute/path/to/disposable-copy.sqlite" \
.venv/bin/python -c 'from server.core.database import rollback_migrations; print(rollback_migrations(target_version=0))'
```

Sind Migrationstabellen befüllt, verweigert die Funktion den Rückweg. Nur nach
separater geprüfter Sicherung kann `allow_data_loss=True` ausdrücklich übergeben
werden. Migration 1 entfernt ihre Projekt-/Medien-/Jobtabellen, nie aber die
OAuth-Tabelle. Anschließend erzeugt der normale Start die Schema-Version wieder
vorwärts. Die automatisierte Down-/Up-Prüfung läuft nur auf temporären SQLite-
Dateien.

Die bestätigten Änderungen, lokalen Prüfergebnisse und offenen Anbieterprüfungen stehen in
[docs/STABILIZATION_RESULT.md](docs/STABILIZATION_RESULT.md). Verträge für neue
Module stehen in [docs/MODULE_DEVELOPMENT.md](docs/MODULE_DEVELOPMENT.md).

### Installation mit uv

Der isolierte Neuinstallationslauf wurde zusätzlich mit `uv` geprüft:

```bash
uv venv --python python3.11 .venv
uv pip install --python .venv/bin/python --index-strategy unsafe-best-match -r requirements-local.lock
uv pip install --python .venv/bin/python -r requirements-test.txt
uv pip check --python .venv/bin/python
```

Die Indexauswahl ist hier für die beiden festgelegten Quellen PyPI und den
offiziellen CPU-PyTorch-Index nötig; die normale pip-Installation oben bleibt möglich.
