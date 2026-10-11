# Stabilisierung: Ergebnis und lokale Abnahme

Stand: 11. Oktober 2026. Dieser Bericht hält den lokal umgesetzten Stand und
die tatsächlich ausgeführten Prüfungen fest. P0–P6 wurden mit drei Workern
(`gpt-6-luna`, Reasoning `high`) umgesetzt und vom Hauptagenten anhand der
Änderungen, isolierter Tests, eines vollständigen Builds und echter lokaler
Browserabläufe geprüft. Reale Anbieter- und Veröffentlichungsdurchläufe sind
weiterhin offen. Medienwerk läuft unter http://localhost:3000.

## Änderungen

- Einstellungen werden normalisiert, validiert und atomar gespeichert.
  `WAVESPEED_AI_KEY` und die älteren Fact-Check-Namen bleiben lesbar; kollidierende
  ausgefüllte Werte werden erhalten. Öffentliche Einstellungen zeigen nur, ob
  ein Schlüssel hinterlegt ist. Jobs erhalten einen festen privaten Snapshot;
  Jobansichten, Logs und Ergebnisobjekte bereinigen Geheimnisse.
- SQLite erhält additive Tabellen für Projekte, Medien, Aufträge, Schritte und
  Ereignisse. Vorhandene OAuth-Datensätze bleiben erhalten. Medien werden unter
  Projekt-UUIDs gespeichert, geprüft und über registrierte Medien-IDs ausgeliefert.
- Jobs verwenden dauerhafte Zustände, Ereignisse, Abbruchsignale und einen
  begrenzten lokalen Worker-Pool. Ein Neustart startet alte Produktionsjobs nicht
  automatisch erneut.
- Quick Creator, Video Tools, Kampagnen sowie die angebundenen Produktionswege
  verwenden gemeinsame Projekt-/Job- und Medienverträge. Neue Kampagnen sind
  pausiert; vor der Aktivierung werden Einstellungen geprüft. Projektversuche
  bekommen eigene Ausgabeordner.
- Konvertierung, Untertitel und TTS werden als Jobs ausgeführt. FFmpeg-Prozesse
  haben Timeouts und lokale Abbruchbehandlung. Externe Anbieteraufrufe erhalten
  begrenzte Timeouts; eine lokale Abbruchmeldung stoppt WaveSpeed-Polling, kann
  aber einen bereits serverseitig gestarteten Anbieterauftrag nicht zurückrufen.
- Ein zusätzlicher, ausdrücklich aufzurufender Migrations-Rückweg ist in
  [MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md) beschrieben. Die normale
  Anwendung ruft ihn nicht auf.

## Sicherung und Migration

P0-Sicherung und Manifest liegen in
`/home/dragos/orca/backups/darter-p0-20261011-103640+0200`. Das ist ein lokaler
Pfad und muss beim Wechsel auf einen anderen Rechner durch eine dortige Sicherung
ersetzt werden. Migration 1 ergänzt Projekttabellen, ohne die OAuth-Tabelle zu
löschen oder umzubauen.

Die Rückwärtsmigration wurde auf einer temporären SQLite-Datei ausgeführt:
Eine getrennte SQLite-Sicherung wurde validiert, der Rückweg verweigerte zuerst
den Abbau befüllter Tabellen, der explizit freigegebene Rückweg entfernte die
Versionszeile und die fünf Migrationstabellen, ließ OAuth-Daten bestehen, und
ein normaler erneuter Start legte Tabellen und Versionszeile wieder an. Die
Sicherung enthielt die vor dem Rückweg gespeicherten Projektdaten weiterhin.
Diese Prüfung verwendete ausschließlich temporäre Dateien und keine Live-Datenbank.

## Tatsächlich ausgeführte Prüfungen

Am 11. Oktober 2026 liefen die Prüfungen mit isolierten Testdaten, SQLite und
kontrollierten lokalen Medienfixtures. Kein echter kostenpflichtiger Anbieter-
oder Publishing-Aufruf wurde ausgeführt.

- Konfiguration, Provideradapter, Projekte/Medien, dauerhafte Queue, Quick Creator,
  Tools, Kampagnen, Workflowadapter, Publishing, HTTP-Integration und Migration
  werden durch die Tests im Verzeichnis `tests/` abgedeckt.
- `tests/test_migration_rollback.py`: 2 Tests bestanden; das Down-/Up-Szenario
  lief gegen temporäre SQLite-Dateien.
- Der vollständige Aufruf `.venv/bin/python -m pytest -q` bestand mit 91 Tests.
- Die kontrollierte Pipelineprüfung führte echte lokale FFmpeg-Erzeugung und
  Muxing aus, registrierte das Ergebnis in SQLite und löste die Medien-ID wieder
  in den Projektordner auf.
- Die Migrationstests prüfen den geschützten Rückweg, eine SQLite-Sicherung,
  erhaltene OAuth-Daten und den erneuten Vorwärtslauf.
- `compileall` für die geänderten Backend-Module wurde ausgeführt.
- Ein sauberer Python-Installationslauf und `pip check` wurden in einer
  temporären Umgebung verifiziert. `npm ci` wurde mit dem vorhandenen Lockfile in
  einem temporären Webverzeichnis erfolgreich ausgeführt.
- `npm run build` bestand in der isolierten, zuvor mit `npm ci` installierten
  Webkopie: TypeScript-Prüfung und sämtliche statischen Seiten erfolgreich.
- Der Hauptagent prüfte einen separaten Backend-/Frontend-Lauf auf Ports
  18008/3001 mit temporärer Datenbank und Dummy-Einstellungen. Die folgenden
  Browserfälle liefen ohne echte Provideraufrufe.

Die genaue Wiederholung der lokalen Prüfungen steht in
[LOCAL_TESTING.md](../LOCAL_TESTING.md). Der historische Ausgangsbefund bleibt in
[PLATFORM_ANALYSIS.md](PLATFORM_ANALYSIS.md) unverändert verfügbar.


## Browser- und Medienprüfung durch den Hauptagenten

| Prüfung | Tatsächliches Ergebnis |
| --- | --- |
| MP4 per Browserformular hochladen und nach 9:16 umwandeln | Job abgeschlossen, Download über registrierte ID; ffprobe: 1080 × 1920, Video und Audio, 1 Sekunde. |
| Neues Ergebnis nach 1:1, zweimaliger Startklick | Genau ein zusätzlicher Konvertierungsjob; ffprobe: 1080 × 1080, Video und Audio. |
| WebSocket im zweiten Lauf gezielt blockiert | Status wurde über HTTP abgefragt; Abschluss und Download erschienen trotzdem. |
| Seitenneuladen eines abgeschlossenen Tools-Jobs | Gespeicherte Job-ID wurde wieder gelesen, Ergebnis verfügbar, keine neue Verarbeitung gestartet. |
| History und Publish | Beide Konvertierungen über denselben registrierten Bestand sichtbar; Videos im Browser mit `readyState=4` abspielbar. |
| Neuer Job nach Abschluss | Formular erneut nutzbar; letzter Download bleibt verfügbar. |
| Settings mit Dummy-Key speichern, neu laden und ausdrücklich löschen | Eingabe bleibt leer, API-Wert leer, Status „Hinterlegt“; danach Status gelöscht. Echte Schlüssel wurden nicht verwendet. |
| Quick Creator ohne erforderliche Schlüssel | Sichtbarer Validierungsfehler; keine Produktion gestartet. |
| Backend-Neustart | Testjob `running` wurde `interrupted`; `awaiting_input` samt Clipper-Auswahl blieb erhalten und erschien nach Wiederaufnahme im Browser. |
| Sicherung wiederherstellen | P0-Datenbank und Konfiguration in temporäres Verzeichnis kopiert; SQLite-Integritätsprüfung `ok`, Konfiguration bytegleich. |
| Normalen lokalen Start wiederholen | `start-local.sh` gestartet, API-Health erreichbar; Schema-Version 1, SQLite `ok`, bisherige Konfiguration bytegleich und alte Smoke-Datei erhalten. |
| Vorhandene Seiten nach Neustart | Dashboard und zwölf Modul-/Einstellungsseiten geöffnet; echte leere Projektzahlen und API-Status statt Beispielwerten. |

Die Browserdaten liegen ausschließlich im temporären Prüfverzeichnis. Die normale
lokale Datenbank enthält keine Testprojekte. Altdateien werden nicht automatisch
registriert; dafür gibt es einen ausdrücklichen Import mit Vorschau.

## Grenzen und nächste Anpassungsrunde

- Echte Gemini-, WaveSpeed-, Pixabay-, VideoFX-Anmeldung, Whisper-Modell-Download
  und YouTube-OAuth-/Upload-Durchläufe wurden nicht durchgeführt. Die simulierten
  Social-Verbindungen sind deaktiviert; TikTok/Instagram melden nicht verfügbar.
- Der bestehende Gemini-Client verwendet weiterhin das abgekündigte SDK
  `google.generativeai`. Die SDK-Umstellung und ein echter kontrollierter
  Anbietercheck sind Folgearbeiten vor einem produktiven KI-Einsatz.
- Der lokale Betrieb verwendet einen Prozess, Threadpool und SQLite. Mehrere
  Backend-Prozesse oder öffentlicher Onlinebetrieb sind nicht Bestandteil der Abnahme.
- Brand-Uploads, Timeline-Bearbeitung und Agentenstudio bleiben als unvollständige
  Bereiche gekennzeichnet. Neue Funktionen, deutsche Oberfläche und Branding
  können nun auf den dokumentierten Verträgen aufgebaut werden.
- Die Tests laufen unter Python 3.11. Hinweise zu `audioop`, dem alten Gemini-SDK
  und FastAPI-Startup-Hooks sind dokumentierte Abkündigungen; sie waren keine
  fehlgeschlagenen Tests. Es fand kein Commit, Push oder Upstream-Merge statt.
