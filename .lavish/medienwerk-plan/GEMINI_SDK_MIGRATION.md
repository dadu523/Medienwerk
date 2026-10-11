# Git-Sicherung und Gemini-SDK-Umstellung

Stand: 11. Oktober 2026. Die beauftragten nächsten Schritte 1 und 2 sind lokal
umgesetzt. Die SDK-Implementierung übernahm ein Worker mit `gpt-6-luna/high`;
der Hauptagent prüfte den Code, ergänzte Tests mit dem tatsächlichen SDK und
prüfte Installation, WebSocket-Verbindung und den Neustart der Anwendung.

## 1. Bisherigen Stand versionieren

Die Stabilisierung wurde auf `dadu523/customize-ai-content-studio` in fünf
getrennten lokalen Commits gesichert:

| Commit | Inhalt |
| --- | --- |
| `18664f6` | Reproduzierbare Installation, lokale Startanleitung, Upstream-Ablauf. |
| `187f364` | Konfigurationsschema, Schlüsselbehandlung und Anbieteradapter. |
| `ee032f4` | Dauerhafte Projekte, Medien, Jobs und bestehende Produktionswege. |
| `9d44d48` | Oberfläche mit gemeinsamen Job- und Medienverträgen. |
| `0a9aefa` | Tests, Analyse, Abnahmebericht und Entwicklungsdokumentation. |

Konfiguration mit Schlüsseln, Datenbank, Produktionsmedien und Sicherungen sind
von Git ausgeschlossen. Die SDK-Umstellung folgt als eigener weiterer Commit.
Es wurde nichts zu GitHub gepusht und kein Upstream-Update eingespielt.

## 2. Gemini auf das aktuelle SDK umstellen

`google-generativeai` und dessen `google-ai-generativelanguage` wurden aus der
lokalen Installation und Lockdatei entfernt. Verwendet wird
`google-genai==2.29.0`, entsprechend dem
[offiziellen SDK-Migrationsweg](https://ai.google.dev/gemini-api/docs/migrate).
Die Lockdatei enthält 94 Anwendungspakete. Das SDK benötigt HTTPX und eine
neuere WebSocket-Bibliothek; lokal ist `websockets==16.1.1` festgehalten.
Andere vorhandene Anwendungspins wurden erhalten.

| Weg | Umsetzung |
| --- | --- |
| Text und JSON | `client.models.generate_content` mit typisierter Konfiguration. Nur Antworttext des ersten Kandidaten wird übernommen; Gedankenparts werden ausgeschlossen. |
| Recherche | Dasselbe SDK mit `GoogleSearch`-Tool statt eigenem REST-Aufruf mit Schlüssel in der URL. |
| Bilder | Gemischte Text-/Bildantworten werden nach Bildparts durchsucht. Vom SDK dekodierte Bytes werden direkt gespeichert. |
| Sprache | Einzelstimme oder zwei Sprecher mit den bestehenden Stimmen und Sprecherlabels; lange Skripte bleiben in Abschnitte unterteilt. PCM wird geprüft und als Mono-WAV mit 16 Bit und der zurückgegebenen Abtastrate gespeichert. |
| Schlüssel und Ressourcen | Expliziter Schlüssel je Client, `vertexai=False`, keine globale Schlüsselkonfiguration. Jeder synchron verwendete SDK-Client wird nach dem Aufruf geschlossen. |
| Timeouts und Quote | 120 Sekunden für Text/Bild/Recherche, 300 Sekunden je Sprachabschnitt. Ein SDK-Versuch; Quote/HTTP 429 löst keinen automatischen Gemini-Neuversuch aus. |

Die bestehenden `GoogleClient`-Methoden bleiben für Pipeline, Agenten und
Workflowadapter nutzbar. Die gesonderten Vertex-Methoden wurden nicht migriert.

Das Bildmodell verwendet jetzt `gemini-2.5-flash-image`: Der vorherige
Preview-Modellname wurde bereits am 15. Januar 2026 abgeschaltet. Text bleibt
bei `gemini-2.5-flash`, Sprache bei `gemini-2.5-flash-preview-tts`. Die Auswahl
neuerer Sprach-/Textmodelle erfordert eine gesonderte Anbieterabnahme: Google
führt das TTS-Modell mit Abschaltung am **17. November 2026**; der Zugang zu
2.5 Flash ist für neue Projekte eingeschränkt. Das stabile Bildmodell hat laut
Google eine Abschaltung am 15. März 2027. Siehe
[offizielle Modell-Abkündigungen](https://ai.google.dev/gemini-api/docs/deprecations).

## Tatsächlich geprüfte Ergebnisse

- Vollständige Testsuite: **116 bestanden** in der vorhandenen `.venv` und in
  der getrennten, anhand beider Lockdateien synchronisierten Python-Umgebung.
- Darin 17 neue Client-Tests und 3 zusätzliche Transporttests des Hauptagenten.
  Letztere verwenden das tatsächliche SDK mit lokalem HTTPX-Transport:
  Anfrageformat, JSON, Suchtool, Bilddekodierung, Einzel-/Mehrsprecher-Audio,
  getrennte Schlüssel bei parallelen Clients, Ressourcenfreigabe und genau
  ein HTTP-Aufruf bei Quote/429. Google wurde dabei nicht kontaktiert.
- `uv pip check`: In beiden Umgebungen sind alle 101 installierten Pakete
  kompatibel; davon 94 Anwendungspakete und 7 zusätzliche Testabhängigkeiten.
- Echter lokaler WebSocket-Handshake gegen Uvicorn mit WebSockets 16.1.1:
  gespeicherter abgeschlossener Testjob als `full_state` empfangen, Ergebnis
  und Ereignissequenz geprüft und Verbindung normal geschlossen. Datenbank
  und Konfiguration lagen ausschließlich in einem temporären Verzeichnis.
- Medienwerk neu gestartet. Backend und Frontend-Proxy liefern Health,
  Projektübersicht und maskierte Konfiguration mit HTTP 200. Im Browser zeigt
  das Dashboard `API Online` und den tatsächlichen leeren Projektbestand.
  Die bisherige `config.json` blieb nach dem Neustart bytegleich.

Echte Generierung, Google-Account-/Modellzugang, Audioqualität und Kosten wurden
nicht geprüft. Vor produktivem KI-Einsatz sind ein kontrollierter Anbietercheck
und die rechtzeitige Ablösung des TTS-Modells erforderlich. Die verbleibenden
Testwarnungen betreffen `audioop` und FastAPI-Startup-Hooks.

## Wiederholen und Rückweg

Installations- und Testbefehle stehen in [LOCAL_TESTING.md](../LOCAL_TESTING.md).
Bei einer bestehenden Umgebung nach Installation des neuen Locks die alten
SDK-Pakete ausdrücklich deinstallieren; normales `pip install -r` entfernt
nicht mehr benötigte Pakete nicht automatisch:

```bash
.venv/bin/python -m pip install -r requirements-local.lock
.venv/bin/python -m pip uninstall google-generativeai google-ai-generativelanguage
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

In der hier vorhandenen Umgebung ohne pip wurde derselbe Wechsel mit `uv pip`
ausgeführt. Ein Rückweg kann in einer getrennten Arbeitskopie von `0a9aefa`
mit dessen eigener Lockdatei und frischer virtueller Umgebung geprüft werden.
Diese SDK-Änderung benötigt keine Datenbankmigration. Der alte Bild-Previewname
wird durch einen Code-Rückweg nicht wieder verfügbar.
