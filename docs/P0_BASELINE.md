# P0: Ausgangsstand und Wiederherstellung

Erfasst am 11. Oktober 2026. Dieses Dokument beschreibt den lokalen Stand vor
den Stabilisierungscodeänderungen. Der vollständige Snapshot liegt außerhalb
des Repositories unter:

`/home/dragos/orca/backups/darter-p0-20261011-103640+0200/`

Das Verzeichnis ist nur für den Benutzer zugänglich (0700); Dateien sind auf
0600 gesetzt. `MANIFEST.json` enthält SHA-256-Prüfsummen, Git-HEAD und Branch,
die damalige Dateiliste des Arbeitsbaums sowie Datenbankinformationen. Der
Snapshot ist lokal und nicht verschlüsselt; er enthält die lokale Konfiguration
und SQLite-Sicherung. Er darf nicht veröffentlicht oder in Git aufgenommen
werden.

## Gesicherter Inhalt

- `source/working-tree.tar.gz`: geänderte und neue Quell- und Dokumentationsdateien,
  einschließlich `AGENTS.md`, `docs/`, `LOCAL_TESTING.md`, `UPSTREAM.md`,
  `start-local.sh` und Webdateien. Ausgeschlossen sind `.git`, virtuelle
  Umgebungen, `node_modules`, Build-Ausgaben, geheime Konfigurationsdateien,
  Laufzeitdaten und generierte Medien.
- `source/tracked-diff.patch`: binärer Diff der getrackten Dateien gegen den
  damaligen `HEAD`. Neue, ungetrackte Dateien liegen im Quellarchiv.
- `data/config.json`: bytegetreue lokale Konfigurationskopie, sofern vorhanden.
- `data/app.db`: mit der SQLite-Online-Backup-API erstellt, während der lokale
  API-Prozess lief. `PRAGMA integrity_check` ergab `ok`; `user_version` war 0.
  Die Datenbank enthielt die Tabelle `oauth_tokens` mit 0 Zeilen.
- `data/workspace-files.tar.gz`: vorhandene Workspace-Dateien ohne die separat
  gesicherte SQLite-Datei, darunter
  `workspace/tools_output/medienwerk-local-smoke_vertical.mp4`.
- `campaigns.json` war zum Aufnahmezeitpunkt nicht vorhanden.

Der Snapshot wurde nach dem Schreiben mit SHA-256 geprüft. Es wurden keine
Schlüsselwerte in die Dokumentation oder die Prüf-Ausgabe übernommen.

## Produktionsstatus bei der Aufnahme

Frontend und Backend liefen auf `127.0.0.1:3000` und `127.0.0.1:8008`. Das
Backend meldete Health `ok`; `/api/campaigns/` lieferte 0 Kampagnen und 0 aktive
Kampagnen. Die Produktionshistorie war leer. Es liefen keine FFmpeg-, Whisper-
oder Pipeline-Unterprozesse. Daher war keine Kampagne zu pausieren. Die
Anwendungsprozesse blieben für die Online-Datenbanksicherung aktiv.

## Laufzeitstand

- Python 3.11.15; virtuelle Umgebung `.venv`.
- 90 installierte Python-Distributionen sind in `requirements-local.lock`
  exakt gepinnt.
- PyTorch 2.14.1+cpu; `torch.version.cuda` war `None`, CUDA nicht verfügbar.
  Die Lockdatei nennt den CPU-Wheel-Index
  `https://download.pytorch.org/whl/cpu`.
- Node.js 26.11.1 und npm 12.2.0; Frontend-Wiederherstellung verwendet
  `npm ci` mit `web/package-lock.json`.
- FFmpeg n9.0.2.
- `start-local.sh` startet Uvicorn und Next.js lokal auf Loopback. Ein belegter
  Port führt zu einer verständlichen Fehlermeldung, statt bestehende Prozesse
  zu beenden.

Versionsstände sind eine Aufnahme und können sich auf dem Rechner ändern.

## Wiederherstellung

1. Zielrepository und Snapshot-Verzeichnis auf demselben Rechner prüfen.
2. Quellarchiv ansehen: `tar -tzf <snapshot>/source/working-tree.tar.gz`.
   Zum Wiederherstellen ausgewählter Dateien das Archiv zunächst in ein
   separates Verzeichnis entpacken und Dateien gezielt übernehmen. Das Archiv
   enthält keinen `.git`-Ordner und keine Laufzeitdaten.
3. `tracked-diff.patch` ist ein zusätzlicher Rückweg für getrackte Änderungen;
   vor Anwendung mit `git apply --check` prüfen. Es stellt keine ungetrackten
   Dateien wieder her.
4. Vor Wiederherstellung der Datenbank das Backend stoppen. Die alte DB-Datei
   beiseite kopieren und `data/app.db` nach `workspace/app.db` kopieren.
   Anschließend Backend starten und die Datenbank prüfen.
5. `data/config.json` nur lokal als `config.json` zurückkopieren. Die Kopie
   enthält Zugangsdaten und bleibt von Git ausgeschlossen.
6. Workspace-Dateien bei Bedarf aus `data/workspace-files.tar.gz` gezielt in
   das Repository entpacken. Vorhandene gleichnamige Dateien nicht blind
   überschreiben.

Keine Sicherung enthält `.git`, Abhängigkeiten oder Browserprofile. Eine
Wiederherstellung dieser Bereiche erfolgt separat über Git und die dokumentierte
Installationsroutine.
