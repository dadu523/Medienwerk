# Medienwerk: Aufbau, Abläufe und Ansatzpunkte für Anpassungen

Stand: 11. Oktober 2026 · Untersucht wurde der aktuelle lokale Arbeitsstand auf `dadu523/customize-ai-content-studio`, einschließlich der Änderungen für den lokalen Start. Die Git-Basis ist `1733f03`; die Untersuchung verändert keine Anwendungsfunktionen.

## 1. Einordnung

Medienwerk ist derzeit eine lokale Anwendung für eine Person, die mehrere Abläufe zur Videoerstellung unter einer gemeinsamen Oberfläche zusammenfasst. Es gibt echte Verarbeitung mit FFmpeg, lokale Transkription mit Whisper und Anbindungen an KI-Anbieter. Die einzelnen Abläufe teilen jedoch noch kein einheitliches Projektmodell. Einige sichtbare Funktionen sind Demonstrationen oder unvollständig angebunden.

Die Oberfläche vermittelt ein zusammenhängendes „Studio“. Im Code bestehen mindestens fünf unterschiedliche Produktionswege: Quick Creator, Magic Clipper, Director Mode, Movie Explainer und VideoFX. Zusätzlich existiert ein separater Ansatz mit Agentenklassen und Studio-Endpunkten, für den die passende Bedienoberfläche weitgehend fehlt. Diese Unterschiede erklären viele der derzeitigen Inkonsistenzen.

**Meine Einschätzung:** Für die Weiterentwicklung ist eine brauchbare Grundlage vorhanden. Der größte Nutzen entsteht zunächst durch einheitliche Projekte, verlässliche Einstellungen und sichtbare Auftragszustände. Reines Umbenennen oder Umgestalten würde die funktionalen Lücken bestehen lassen.

### Was die Aussagen belegen

| Kennzeichnung | Bedeutung |
| --- | --- |
| Lokal geprüft | Im vorherigen Test tatsächlich ausgeführt: Seitenaufrufe, Build, Einstellungen speichern, WebSocket-Verbindung und 9:16-Konvertierung samt Download. |
| Im Code umgesetzt | Der Ablauf und die Aufrufe sind im Quellcode vorhanden. Das beweist keinen erfolgreichen vollständigen Lauf mit einem externen Anbieter. |
| Code-Befund | Ein Widerspruch, fehlender Aufruf oder Platzhalter ist anhand der Dateien nachvollziehbar. |
| Einschätzung | Eine Empfehlung für die Weiterentwicklung, die wir an deine Wünsche anpassen können. |

Es wurde für diese Analyse keine kostenpflichtige KI-Produktion, Veröffentlichung auf Social Media oder neue Kampagne ausgelöst. Insbesondere Modellverfügbarkeit, Qualität, Laufzeiten und Anbieterpreise sind durch diese Untersuchung nicht bestätigt. Die Bilder in der visuellen Ausgabe zeigen echte lokale Seiten; ihre Platzhalterwerte sind keine Messdaten.

## 2. Technischer Aufbau

| Ebene | Umsetzung | Aufgabe |
| --- | --- | --- |
| Oberfläche im Browser | React 19.2.4, TypeScript, Next.js 16.4.0 | Eingaben, Navigation, Ergebnisanzeige und laufende Fortschrittsmeldungen. |
| Gestaltung | Tailwind CSS 4, Outfit-Schrift, Lucide-Icons | Dunkle Oberfläche, transparente Karten, türkise Akzente. |
| Lokaler Webserver | Next.js auf Port 3000 | Liefert die Oberfläche; leitet `/api/...` zum Backend weiter. |
| Backend | FastAPI, Pydantic, Uvicorn auf Port 8008 | Nimmt Aufträge entgegen, liest Einstellungen, liefert Dateien und startet Verarbeitung. |
| Hintergrundaufträge | Python-Threadpool mit zwei Arbeitsthreads | Längere Aufträge laufen außerhalb der eigentlichen API-Antwort. |
| Live-Verbindung | WebSockets | Der Server sendet Status, Fortschritt, Protokolle und Ergebnisse an den Browser. |
| Medienverarbeitung | FFmpeg, ffmpeg-python, pydub, pysubs2, teilweise MoviePy | Schnitt, Skalierung, Tonmischung, Untertitel und fertige Videodateien. |
| Spracherkennung | OpenAI Whisper auf dem lokalen Rechner | Wandelt vorhandenes Audio in Text und Zeitmarken um. |
| Dateispeicherung | Lokales Dateisystem und JSON | Einstellungen, Projektdateien, Kampagnen, Zwischenprodukte und Videos. |
| Datenbank | SQLite über SQLAlchemy | Bisher nur die Tabelle für Social-OAuth-Tokens. |

Ein **API-Endpunkt** ist eine Adresse, über die die Oberfläche eine bestimmte Aktion beim Backend anfordert. Ein **Job** ist ein länger laufender Auftrag. Ein **Worker** ist der Hintergrundteil, der diesen Auftrag verarbeitet. Eine **Pipeline** ist eine festgelegte Folge von Arbeitsschritten. Ein **Provider** ist ein externer oder lokaler Anbieter für Text, Stimmen, Bilder oder Videos.

Beim lokalen Start sind Next.js und FastAPI zwei getrennte Prozesse. `start-local.sh` startet beide und bindet sie an `127.0.0.1`. Die Oberfläche nutzt relative API-Adressen. Dadurch entscheidet der Webserver über das Ziel; der Browser muss die Backend-Adresse nicht selbst kennen. `websocketUrl()` verwendet den aktuellen Host und wählt abhängig von HTTP oder HTTPS die passende WebSocket-Verbindung.

Quellen: [web/package.json:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/package.json:1), [web/next.config.ts:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/next.config.ts:1), [start-local.sh:1](/home/dragos/orca/workspaces/Medienwerk/darter/start-local.sh:1), [server/main.py:16](/home/dragos/orca/workspaces/Medienwerk/darter/server/main.py:16), [web/src/lib/api.ts:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/lib/api.ts:1), [server/core/queue.py:11](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/queue.py:11).

### Welche Dateien welche Verantwortung haben

| Bereich | Zentrale Dateien | Bedeutung für spätere Änderungen |
| --- | --- | --- |
| Seiten und Navigation | `web/src/app/`, `Sidebar.tsx`, `layout.tsx` | Hier ändern wir Menüs, Namen, Inhalte und Bedienabläufe. |
| Design | `web/src/app/globals.css` | Zentrale Farben und gemeinsame Karten-, Formular- und Button-Stile. Viele Seiten haben zusätzliche direkte Farbwerte. |
| Einstellungen im Browser | `web/src/context/ConfigContext.tsx` | Lädt die globale Konfiguration und speichert sie zurück. |
| Start und API-Zuordnung | `server/main.py` | Bindet elf Routergruppen ein und startet den Scheduler. |
| Einzelne API-Aktionen | `server/routers/` | Übersetzt Browser-Eingaben in Aufträge oder direkte Verarbeitung. |
| Auftragszustände | `server/core/queue.py` | Job-IDs, Status, Worker, WebSockets und Abbruchsignale. |
| Quick Creator | `pipeline.py` | Große Produktionspipeline mit 14 Schritten; rund 880 Zeilen. |
| KI-Anbindungen | `api_clients.py` | Text-Routing, Gemini, WaveSpeed, Pixabay und NewsAPI; rund 850 Zeilen. |
| Agentenansatz | `agents.py` | Feste Rollen für Schreiben, Szenen, Bilder, Videos und Montage. |
| Bestehende Videos | `pipeline_shorts.py`, `director_engine.py`, `explainer_engine.py` | Drei unterschiedliche Arten der Bearbeitung von vorhandenem Material. |

Die API-Schicht ist bereits nach Funktionen getrennt. Die größte Kopplung liegt in den globalen Einstellungen, den gemeinsamen KI-Clients und den Dateipfaden. Die Bezeichnung „Agent“ steht hier für Python-Klassen mit festgelegten Arbeitsschritten und Prompts; die Ausführung wird durch den Code vorgegeben.

## 3. Funktionsübersicht

Die Anwendung hat 13 Seitenrouten; die Seitenleiste verlinkt zwölf davon. Der zusätzliche Agentenbereich liegt unter `/studio/agent`.

| Bereich | Tatsächliche Umsetzung | Gegenwärtige Grenze |
| --- | --- | --- |
| Dashboard `/` | Navigation und gestaltete Übersicht. | Kennzahlen und letzte Ergebnisse sind fest eingetragene Beispieldaten. |
| Quick Creator `/studio` | Formular, API-Auftrag, 14-Schritte-Pipeline, Live-Protokolle. | Gesamtlauf mit KI nicht bestätigt; Ergebnisse liegen außerhalb der von der Historie erwarteten Ordner. |
| Magic Clipper `/clipper` | URL oder Upload → Transkript → Vorschläge → Auswahl → Schnitt und Untertitel. | Englisch fest vorgegeben; Timeline teilweise Attrappe; Vorschlagsdaten nur begrenzt validiert. |
| Director Mode `/director` | Download, Stille entfernen, Worterkennung, Zoom-/SFX-Regeln. | Regelsystem mit englischen Schlüsselwörtern; Ergebnisse fehlen in der Historie. |
| Movie Explainer `/explainer` | Bestehendes Video → Transkript → Erzählszenen → TTS → Montage. | Wiederverwendung nach URL berücksichtigt geänderte Sprache oder Stimme nicht ausreichend. |
| VideoFX Flow `/videofx` | Automatisiert einen sichtbaren Chrome-Browser mit Playwright. | Benötigt lokale Google-Anmeldung; abhängig von Bedienelementen einer fremden Website. |
| Auto-Pilot `/campaigns` | Kampagnen anlegen, pausieren, löschen; Scheduler vorhanden. | Scheduler greift auf ein fehlendes `google_client`-Attribut zu. |
| Brand Assets `/brand` | Sichtbare Seite ist „Coming Soon“. Backend kann Logo/Intro/Outro speichern. | Upload-Bedienung fehlt; Branding wird nur in der Quick-Pipeline eingebaut. |
| History `/history` | Durchsucht Ordner und bietet Wiedergabe, Downloads und Löschen. | Erkennt nur bestimmte Ordner- und Dateinamen; kein zentrales Projektregister. |
| Video Tools `/tools` | Untertitel, Formatumwandlung, Sprachfunktion. | 9:16-Konvertierung lokal geprüft; Sprachfunktion ruft eine fehlende Methode auf; 1:1 wird im Backend nicht separat behandelt. |
| Publish `/publish` | Podcast-Bibliothek, Metadatenformular, echter YouTube-Uploadpfad. | Desktop-OAuth separat von simulierten Social-Tokens; Plattformauswahl steuert keine vollständige Mehrfachveröffentlichung. |
| Settings `/settings` | API-Schlüssel, Anbieter, Modelle und Untertiteloptionen speichern. | Uneinheitliche Namen; einige Einstellungen werden nicht verwendet oder sind nicht bedienbar. |
| AI Orchestrator `/studio/agent` | Sichtbarer Hinweis „Coming Soon in Pro Enterprise Edition“. | Studio-API und Agentenklassen werden auf dieser Seite nicht angebunden. |

Quellen: [web/src/components/Sidebar.tsx:10](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/components/Sidebar.tsx:10), [web/src/app/page.tsx:73](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/page.tsx:73), [web/src/app/brand/page.tsx:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/brand/page.tsx:1), [web/src/app/studio/agent/page.tsx:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/studio/agent/page.tsx:1), [server/main.py:40](/home/dragos/orca/workspaces/Medienwerk/darter/server/main.py:40).

## 4. Was bei einem Auftrag geschieht

Der typische Ablauf lautet: Eingabe im Browser → HTTP-Anfrage an `/api/...` → Validierung durch Pydantic → Job-ID erstellen → Hintergrundauftrag starten → Fortschritt über WebSocket senden → Ergebnis als Dateipfad zurückgeben → Datei über den Medien-Endpunkt abspielen oder herunterladen.

Die API antwortet bei diesen Aufträgen schon mit einer Job-ID, bevor die Produktion fertig ist. Die Oberfläche muss anschließend den richtigen Job verfolgen. Der Job-Speicher `_JOBS` ist ein Python-Dictionary im Arbeitsspeicher. Bei einem Backend-Neustart gehen Jobzustände und Protokolle verloren, während bereits geschriebene Dateien bestehen bleiben. Es gibt keine dauerhafte Warteschlange mit Wiederaufnahme und keine automatische Bereinigung alter Job-Einträge.

Zwei Arbeitsthreads können gleichzeitig Jobs verarbeiten. Das ist keine Garantie von nur zwei gleichzeitig laufenden Anbieteranfragen: Der Agentenansatz startet zusätzliche Pools mit fünf Threads, und `/api/studio/render` sowie VideoFX-Login verwenden eigene Threads außerhalb der zentralen Warteschlange.

Es gibt drei Nachrichtenarten: `full_state` enthält den Zustand beim Verbinden, `update` enthält neue Zustandsfelder, `log` enthält Meldungen. Bei `log` existieren zwei verschiedene Formate: einmal `data`, einmal `message` und `progress`. Verschiedene Seiten erwarten unterschiedliche Varianten. Die reine WebSocket-Verbindung wurde geprüft; alle möglichen Meldungs- und Wiederverbindungsfälle wurden nicht ausgeführt.

Quellen: [server/core/queue.py:13](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/queue.py:13), [server/core/queue.py:39](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/queue.py:39), [server/core/queue.py:119](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/queue.py:119), [server/core/queue.py:159](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/queue.py:159), [server/routers/studio.py:158](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:158), [web/src/app/studio/page.tsx:182](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/studio/page.tsx:182), [web/src/app/explainer/page.tsx:45](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/explainer/page.tsx:45).

## 5. Quick Creator: Aus einem Thema wird ein Video

Der Browser sammelt Thema, Inhaltstyp, Stil, Stimme, Seitenverhältnis, Hintergrundmodus und Zusatzoptionen. `/api/generate/quick` erzeugt einen Job. Der Worker liest die globale Konfiguration, überschreibt einzelne Werte für diesen Auftrag und ruft `Pipeline.run()` auf.

| Schritt | Was der Code tut |
| --- | --- |
| 1. Deep Research | Recherchetext erzeugen, bei Gemini mit Google-Suche; optional NewsAPI-Kontext. |
| 2. Fact Check Research | Ein weiteres KI-Review, wenn aktiviert. Keine unabhängige Garantie geprüfter Fakten. |
| 3. Revise Research | Recherche anhand des Reviews überarbeiten. |
| 4. Podcast Script | Skript abhängig von Inhaltstyp, Sprache, Stil und gewünschter Länge schreiben. |
| 5. Generate Thumbnail | Optional zwei Bilder erzeugen und nebeneinander montieren. |
| 6. Analyze Tone | Aktuell nur den Schritt als erledigt markieren; keine eigentliche Analyse. |
| 7. Audio (TTS) | Skript vertonen; Gemini kann passend formatierten Podcasttext mit zwei Stimmen sprechen. |
| 8. Generate Timed Images | Optional Bilder zu Zeitabschnitten erzeugen. |
| 9. Video Generation | KI-Clips oder Pixabay-Material erzeugen beziehungsweise laden. |
| 10. Add Background Music | Vorhandene lokale Musik mit Sprache mischen. |
| 11. Create Final Video | Bild und Ton montieren, Untertitel einbrennen, optional Branding. |
| 12. Generate SEO Metadata | Titel, Beschreibung und Tags erzeugen. |
| 13. Generate Timestamps | KI-Kapitelüberschriften mit Wortzeitmarken verknüpfen. |
| 14. Generate Snippets | Ganze 60-Sekunden-Abschnitte als zusätzliche Clips schneiden. |

**Wiederverwendung:** Viele Schritte überspringen die Erzeugung, sobald die erwartete Datei existiert. Das kann Zeit und Anbieteraufrufe sparen. Es fehlt aber ein Vergleich, ob sich Eingaben oder Einstellungen seit der letzten Erzeugung geändert haben. Gleichnamige Themen verwenden denselben Ordner. So können neue Einstellungen auf alte Zwischenprodukte treffen.

**Ergebnisort:** `output_dir = safe_topic` legt den Themenordner direkt im Projektverzeichnis an. Das fertige Video heißt `final_podcast_video.mp4`. Historie und Publish suchen Podcasts dagegen unter `workspace/`. Dieser Unterschied ist eine konkrete Integrationslücke.

**Fortschritt:** Die Pipeline meldet Werte je Schritt, zum Beispiel `0.2` und `1.0`. Die API übernimmt sie direkt als Gesamtfortschritt und verwendet den Schrittindex nicht. Deshalb kann die Anzeige mehrfach 100 Prozent erreichen. Der Quick Creator wertet beim anfänglichen `full_state` außerdem nicht alle abschließenden Zustände aus; ein sehr früh abgeschlossener Job kann dadurch im Browser als laufend stehen bleiben.

**Optionen:** `OMNICHANNEL` wird gespeichert, aber in der Produktionspipeline nicht ausgewertet. `VISUAL_STYLE` wird vom Formular gesetzt, jedoch dort nicht als zentrale Vorgabe gelesen. Das Bildzählfeld aktiviert `GENERATE_TIMED_IMAGES` nicht automatisch. Ein gewählter Stil oder Schalter beweist deshalb noch keine entsprechende Verarbeitung.

Quellen: [server/routers/generation.py:48](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:48), [pipeline.py:251](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:251), [pipeline.py:363](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:363), [pipeline.py:380](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:380), [pipeline.py:585](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:585), [pipeline.py:780](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:780), [server/routers/generation.py:82](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:82), [web/src/app/studio/page.tsx:185](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/studio/page.tsx:185).

## 6. Magic Clipper: Aus vorhandenem Material werden Shorts

Der Clipper hat zwei Phasen. Zunächst wird eine YouTube-URL heruntergeladen oder eine lokale Datei gespeichert. Whisper liefert Wörter mit Zeitmarken. Der Code bündelt sie ungefähr alle zehn Sekunden. Ein Textmodell bekommt die ersten 15.000 Zeichen dieses Transkripts und soll interessante Ausschnitte mit Start, Ende, Titel, Begründung, Scores und SEO-Daten vorschlagen.

Die Oberfläche zeigt die Vorschläge zur Auswahl. Erst ein zweiter Aufruf an `/api/clipper/render` verarbeitet die ausgewählten Ausschnitte. Derselbe Job wird dabei weiterverwendet. Die ursprüngliche Analyse ist bei Fortschritt `0.6` im Zustand „Auswahl“, also noch kein fertiges Video.

Beim Rendern wird mit OpenCV ungefähr zweimal pro Sekunde nach Gesichtern gesucht. Der Bildausschnitt richtet sich am größten erkannten Gesicht aus. Bei größeren Positionsänderungen entstehen neue Zuschnitte. Anschließend wird auf 720 × 1280 skaliert, optional Pixabay-Material eingeblendet, lokale Musik gemischt und eine neue Transkription für eingebrannte Untertitel erstellt.

Die Bezeichnung „Active Speaker Tracking“ ist weitergehend als diese Umsetzung: Der Code erkennt Gesichter und wählt das größte Gesicht; er erkennt nicht anhand des Audios, welche Person tatsächlich spricht. Auch die „Virality“-Scores sind vom Textmodell vorgeschlagene Zahlen, keine beobachteten Leistungsdaten.

Die Analyse und Untertitel sind auf „English“ festgelegt. Spätere Teile eines langen Videos gelangen nach der Begrenzung des Transkripts unter Umständen gar nicht in die KI-Auswahl. Start und Ende kommen aus einem JSON-Vorschlag; es fehlt eine durchgängige Prüfung gegen Videolänge und zulässige Clipdauer.

Der Timeline-Editor zeigt eine simulierte Vorschau und dekorative Spuren. Die Zustände für Start- und Endgriffe sind vorhanden, werden aber durch keine Bedienung verändert. „Save Cuts“ liefert deshalb die vorhandenen Zeitwerte zurück. Für einen echten Editor brauchen wir eine Videoverbindung, bedienbare Zeitgrenzen und eine verlässliche Vorschau.

Quellen: [pipeline_shorts.py:32](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline_shorts.py:32), [pipeline_shorts.py:112](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline_shorts.py:112), [pipeline_shorts.py:160](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline_shorts.py:160), [pipeline_shorts.py:204](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline_shorts.py:204), [server/routers/clipper.py:91](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/clipper.py:91), [web/src/components/TimelineEditor.tsx:14](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/components/TimelineEditor.tsx:14).

## 7. Die übrigen Produktionswege

### Director Mode

Dieser Modus bearbeitet ein vorhandenes Video. Er lädt es herunter, sucht stille Stellen mit pydub und schneidet sie heraus. Für zusätzliche Effekte transkribiert Whisper den Ton. Eine feste englische Wortliste wie „money“, „secret“ und „viral“ löst geplante Zoomstellen und Soundeffekte aus. Das ist ein regelbasierter Schnittablauf. Ein frei bedienbarer Mehrspur-Editor ist auf dieser Seite nicht vorhanden.

Soundeffekte benötigen `assets/sfx/swoosh.wav`. Ohne diese Datei entfällt der Effekt. Das Ergebnis liegt unter `workspace/director_<job-id>/final_master.mp4`; die Historie sucht diesen Dateinamen nicht. Auch das als Punch-in bezeichnete Filterverhalten sollte separat mit Testmaterial geprüft werden, bevor wir seine Bildwirkung als fertig betrachten.

Quelle: [server/core/director_engine.py:10](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/director_engine.py:10).

### Movie Explainer

Ein vorhandenes Video wird geladen, sein Ton extrahiert und lokal mit Whisper `tiny` transkribiert. Ein Textmodell formuliert daraus eine Liste von Erzählszenen mit Originalzeitmarken. Jede Szene bekommt neue Sprache und Untertitel; entsprechende Ausschnitte des Originalvideos werden montiert. Die gewünschte Gesamtdauer ist eine Prompt-Vorgabe, keine exakt berechnete Zielzeit.

Der Ausgabeordner wird aus einem Hash der Quell-URL beziehungsweise des Pfads gebildet. Dateien werden erneut verwendet, wenn sie vorhanden sind. Sprache, Stimme, Modell und Zieldauer sind nicht Teil dieses Schlüssels. Eine Änderung dieser Optionen kann deshalb alte Skripte oder Szenen wiederverwenden. Beim Schnitt wird die TTS-Dauer verwendet; die berechnete Original-Szenendauer bestimmt den Schnitt nicht direkt.

Das Ergebnis liegt unter `outputs/explainer_<hash>/final_explainer.mp4`. Das Backend nimmt es in die Historie auf, während die Oberfläche nur die Typen Podcast und Clipper kennt und andere Typen entsprechend falsch beschriftet.

Quellen: [server/core/explainer_engine.py:13](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/explainer_engine.py:13), [server/core/explainer_engine.py:103](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/explainer_engine.py:103), [server/core/explainer_engine.py:140](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/explainer_engine.py:140), [server/routers/generation.py:192](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:192), [web/src/app/history/page.tsx:15](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/history/page.tsx:15).

### VideoFX Flow

Hier wird eine fremde Website über Playwright bedient. Ein sichtbarer Chrome-Browser öffnet Google VideoFX, verwendet ein gespeichertes Browserprofil, trägt den Prompt ein und wartet auf ein Video oder einen Download. Browserbilder können als Base64 über WebSocket zur Oberfläche übertragen werden.

Das ist eine Browserautomatisierung und verwendet keine eigene stabile VideoFX-API. Sie hängt von Chrome, der lokalen Anmeldung und passenden Selektoren der Website ab. Die Login-API meldet den Start des Hintergrundthreads; daraus lässt sich noch kein erfolgreicher Login ableiten. Ergebnisse landen unter `videofx_outputs/` und werden von der Historie nicht erfasst.

Quellen: [server/core/videofx_client.py:14](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/videofx_client.py:14), [server/core/videofx_client.py:38](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/videofx_client.py:38), [server/routers/videofx.py:15](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/videofx.py:15).

### Auto-Pilot und Kampagnen

Kampagnen werden in `campaigns.json` gespeichert. Beim Backend-Start beginnt ein Hintergrundthread, der alle 60 Sekunden prüft, welche aktive Kampagne fällig ist. Eine neu angelegte Kampagne ist sofort fällig. Der Scheduler soll einen Titel erzeugen und denselben Quick-Creator-Worker mit passenden Vorgaben starten.

Dieser Ablauf enthält einen klaren Fehler: `trend.google_client` wird verwendet, aber `TrendAgent` oder dessen Basisklasse legen dieses Attribut nicht an. Der Fehler wird abgefangen und die nächste Ausführung um fünf Minuten verschoben. Außerdem ruft die Trendfunktion `NewsApiClient.get_top_headlines()` auf, obwohl dieser Client nur `get_news()` anbietet. Der separate Endpunkt für Trendthemen verwendet zusätzlich eine undefinierte Variable `job_id`.

Es gibt keine anschließende automatische Veröffentlichung im Scheduler. „Kampagne“ bedeutet hier zunächst geplante Produktion. Mehrere Backend-Prozesse könnten dieselbe Kampagne mehrfach auslösen, weil weder dauerhafte Sperren noch ein verteilter Scheduler vorhanden sind.

Quellen: [server/core/scheduler.py:35](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/scheduler.py:35), [server/core/scheduler.py:65](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/scheduler.py:65), [server/core/scheduler.py:89](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/scheduler.py:89), [agents.py:27](/home/dragos/orca/workspaces/Medienwerk/darter/agents.py:27), [api_clients.py:145](/home/dragos/orca/workspaces/Medienwerk/darter/api_clients.py:145), [server/routers/generation.py:117](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:117).

### Studio-API und Agentenklassen

Die Studio-API hat Endpunkte für Chat, Skript, Storyboard und Rendering. Der Chat erkennt das Textsignal `FINAL_SCRIPT_READY:`. Die Agentenklassen können Recherche, Dialogskript, Szenenprompts, Bilder, Videos und Montage abarbeiten. Es gibt Fallbacks, etwa schwarze Ersatzbilder oder Standbildvideos, wenn Anbieteraufrufe scheitern.

Die aktuelle Agentenseite ruft diese Endpunkte nicht auf. Der Storyboard-Endpunkt liefert einen Dateipfad zurück, weil er `generate_storyboard()` verwendet; das spätere Render-Schema erwartet dagegen eine Liste von Szenen. Das Studio-Rendering läuft in einem eigenen Thread ohne zentrale Job-ID und schreibt `final_production.mp4`, das die Historie ebenfalls nicht erkennt. Diese Teile sollten zuerst zu einem durchgängigen Ablauf verbunden werden.

Quellen: [server/routers/studio.py:41](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:41), [server/routers/studio.py:107](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:107), [server/routers/studio.py:158](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:158), [agents.py:137](/home/dragos/orca/workspaces/Medienwerk/darter/agents.py:137), [agents.py:172](/home/dragos/orca/workspaces/Medienwerk/darter/agents.py:172), [agents.py:257](/home/dragos/orca/workspaces/Medienwerk/darter/agents.py:257), [web/src/app/studio/agent/page.tsx:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/studio/agent/page.tsx:1).

## 8. Anbieter und Einstellungen

| Aufgabe | Im Code vorhandene Wege | Einschränkung |
| --- | --- | --- |
| Text | Gemini, WaveSpeed, lokales Ollama | WaveSpeed-Text liest einen anderen Schlüsselnamen als die Oberfläche speichert. |
| Recherche | Gemini mit Google-Suche, optional NewsAPI | Serper-Schlüssel wird in der Oberfläche angeboten, hat aber keinen entsprechenden Verarbeitungsweg. |
| Stimmen | Gemini-TTS, WaveSpeed | Video-Tools-TTS ruft `generate_speech()` auf; vorhanden ist `text_to_speech()`. |
| Bilder | Gemini, WaveSpeed, zusätzliche Vertex-Methode | Nicht alle Wege sind mit Formularen verbunden; Agenten lesen teils falsche Schlüssel. |
| Neue Videoclips | WaveSpeed, Vertex-Zweig | Anbieter- und Modellaufrufe sind vorhanden, aber nicht praktisch bestätigt. |
| Stockmaterial | Pixabay | Benötigt Schlüssel; wird je nach Produktionsweg unterschiedlich verwendet. |
| Transkription | Whisper `base` oder `tiny` | Lokal; Modelle, Sprache und Verhalten unterscheiden sich zwischen den Modulen. |
| Google VideoFX | Lokale Chrome-Automatisierung | Eigenständiger Weg mit Browserprofil und Anmeldung. |

`GoogleClient` ist trotz seines Namens auch der Router für andere Textanbieter. Das erschwert das Verständnis: Eine neue Textfunktion muss aktuell über eine Klasse mit Google-Namen gehen, selbst wenn sie Ollama verwendet. Modellnamen für einige Google-Wege sind Konstanten in `api_clients.py`; die WaveSpeed-Modelle sind teilweise über Einstellungen veränderbar.

Alle Einstellungen befinden sich in einer globalen `config.json`. Die Oberfläche lädt diese gesamte Konfiguration und sendet beim Speichern das gesamte Objekt zurück. Es gibt keine persönlichen Einstellungen pro Benutzer und keinen Konfigurationsbereich pro Projekt. Einige APIs lesen die Konfiguration zu Beginn, andere Produktionsphasen lesen sie später erneut. Änderungen während laufender Aufträge können so unterschiedlich wirken.

Sichtbare Lücken sind `WAVESPEED_API_KEY` gegenüber `WAVESPEED_AI_KEY`, `FACT_CHECK` gegenüber `FACT_CHECK_ENABLED` beim Initialisieren des Formulars und unterschiedliche Darstellungen des Seitenverhältnisses. Ollama-Adresse und Modell sind im Backend vorgesehen, haben auf der aktuellen Settings-Seite aber keine eigenen Eingabefelder. „Ollama auswählen“ macht die komplette Medienproduktion noch nicht lokal: Stimmen, Bilder oder Videos können weiterhin andere Anbieter benötigen.

Quellen: [config.py:24](/home/dragos/orca/workspaces/Medienwerk/darter/config.py:24), [web/src/context/ConfigContext.tsx:14](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/context/ConfigContext.tsx:14), [web/src/app/settings/page.tsx:45](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/settings/page.tsx:45), [api_clients.py:171](/home/dragos/orca/workspaces/Medienwerk/darter/api_clients.py:171), [api_clients.py:206](/home/dragos/orca/workspaces/Medienwerk/darter/api_clients.py:206), [agents.py:175](/home/dragos/orca/workspaces/Medienwerk/darter/agents.py:175), [server/routers/tools.py:92](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/tools.py:92).

## 9. Daten, Dateien und Historie

| Speicher | Was dort liegt | Was bei Neustart oder Änderung passiert |
| --- | --- | --- |
| `config.json` | Globale Einstellungen und API-Schlüssel. | Bleibt erhalten; unverschlüsselt; von Git ignoriert. |
| `campaigns.json` | Kampagnen, Aktivierung und nächste Ausführung. | Bleibt erhalten; derzeit nicht ausdrücklich von Git ausgeschlossen. |
| `workspace/app.db` | Social-Token-Tabelle. | Bleibt erhalten; keine Tabelle für Projekte oder Jobs. |
| `_JOBS` im RAM | Laufende/abgeschlossene Aufträge und Logs. | Geht beim Backend-Neustart verloren. |
| `<Thema>/` im Projektordner | Quick-Creator-Zwischenprodukte und Endvideo. | Wiederverwendung nach Dateiexistenz; nicht in der normalen Historie gefunden. |
| `workspace/clipper_<id>/` | Quelle, Clips, Untertitel, finale Shorts. | Finale `Final_*.mp4` werden von der Historie erkannt. |
| `workspace/director_<id>/` | Schnitt-Zwischenprodukte und `final_master.mp4`. | Finale Datei wird von der Historie nicht erkannt. |
| `outputs/explainer_<hash>/` | Transkript, Skript, Szenen und Endvideo. | Backend erkennt den Explainer; Cache berücksichtigt geänderte Optionen nicht ausreichend. |
| `videofx_outputs/`, `agent_workspace/` | VideoFX- oder Agentenergebnisse. | Werden von der aktuellen Historie nicht durchsucht. |
| `assets/`, Browserprofil, OAuth-Dateien | Markenmedien und Anmeldedaten. | Unterschiedliche Speicherorte und unterschiedliche Ausschlüsse in Git. |

Die Historie ist keine Datenbankabfrage über alle Produktionen. Sie durchsucht Verzeichnisse, erkennt wenige feste Dateinamen und leitet Typen aus Ordnernamen ab. Die Publish-Bibliothek hat zusätzlich eine eigene, engere Suchlogik für Podcastdateien. Deshalb können zwei Seiten unterschiedliche Ergebnisse anzeigen.

**Ansatzpunkt:** Ein Projekt sollte eine eindeutige ID, einen Typ, einen Titel, die verwendeten Einstellungen, Quellmedien, Ausgabe-Dateien und zugehörige Jobs haben. Ein Dateipfad wäre dann eine Eigenschaft dieses Projekts. Historie, Dashboard und Publish könnten denselben Bestand anzeigen.

Quellen: [server/core/database.py:5](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/database.py:5), [server/routers/generation.py:147](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:147), [server/routers/publish.py:18](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/publish.py:18), [pipeline.py:257](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:257), [agents.py:294](/home/dragos/orca/workspaces/Medienwerk/darter/agents.py:294), [.gitignore:23](/home/dragos/orca/workspaces/Medienwerk/darter/.gitignore:23).

## 10. Oberfläche, Design und Sprache

Die gemeinsame Gestaltung verwendet `--bg-main`, `--bg-glass`, `--border-glass` und `--accent`. Die Karten und Formulare sind teilweise als gemeinsame CSS-Klassen gestaltet. Zusätzliche Farben und Komponenten werden direkt in den einzelnen Seiten definiert. Eine zentrale Farbänderung wirkt deshalb nicht überall vollständig.

Das Layout enthält eine feste Seitenleiste mit etwa 256 Pixeln Breite und einen separat scrollenden Inhaltsbereich. Es ist auf einen Desktop-Arbeitsplatz ausgerichtet; eine eigene mobile Navigation fehlt. Die meisten Texte stehen direkt auf Englisch im JSX, und die HTML-Sprache ist `en`. Es gibt keine zentrale Übersetzungsdatei. Oberfläche übersetzen und erzeugte Inhalte auf Deutsch konfigurieren sind zwei unterschiedliche Aufgaben.

Die Seitenleiste zeigt „API Connected“ immer an, ohne den Backend-Zustand abzufragen. Das Dashboard hat echte Navigationslinks, aber feste Zahlen und feste Beispielprojekte. Schaltflächen wie „View All“ sind dort nicht mit einer Aktion verbunden. Für eine verlässliche Oberfläche sollten Status und Kennzahlen aus echten Daten kommen oder als Beispiele erkennbar sein.

Der lokale Start hat fehlende Icons und den Clipper-Typfehler beseitigt. Das bedeutet, dass die Seiten gebaut werden können; es bestätigt nicht automatisch die Verarbeitung hinter jeder Option.

Quellen: [web/src/app/globals.css:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/globals.css:1), [web/src/app/layout.tsx:24](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/layout.tsx:24), [web/src/components/Sidebar.tsx:29](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/components/Sidebar.tsx:29), [web/src/components/Sidebar.tsx:66](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/components/Sidebar.tsx:66), [web/src/app/page.tsx:73](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/page.tsx:73).

## 11. Veröffentlichungen und Anmeldungen

Es existieren zwei verschiedene YouTube-Wege. `/api/publish/youtube` enthält einen echten Upload über die Google-Clientbibliothek. Dafür werden `client_secrets.json` und gegebenenfalls `token.pickle` gebraucht. Der OAuth-Ablauf öffnet einen Browser auf dem lokalen Rechner und verwendet Port 8080. Er ist auf einen Desktopbetrieb zugeschnitten.

Die Endpunkte unter `/api/social` simulieren dagegen Teile der Verbindung. Der YouTube-Callback speichert erfundene Tokenwerte; der dortige Publish-Endpunkt liefert eine feste Beispiel-ID. TikTok und Instagram liefern Beispiel-Weiterleitungsadressen. Diese Token-Tabelle wird nicht vom echten YouTube-Upload verwendet. Die beiden Systeme teilen deshalb keinen tatsächlichen Anmeldezustand.

Die Publish-Oberfläche besitzt eine Plattformauswahl, sendet bei der Veröffentlichung jedoch an den YouTube-Endpunkt. Ein produktiver TikTok- oder Instagram-Upload ist in diesem Stand nicht umgesetzt. Im Scheduler gibt es keinen Aufruf zur Veröffentlichung fertiger Videos.

Quellen: [server/routers/publish.py:82](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/publish.py:82), [server/routers/social.py:28](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:28), [server/routers/social.py:34](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:34), [server/routers/social.py:59](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:59), [web/src/app/publish/page.tsx:41](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/publish/page.tsx:41), [server/core/scheduler.py:125](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/scheduler.py:125).

## 12. Grenzen beim Betrieb

Der aktuelle lokale Betrieb passt zum vorhandenen Vertrauensmodell: Die Anwendung setzt voraus, dass die bedienende Person auch auf den Rechner zugreifen darf. Es gibt keine Anmeldung an Medienwerk, keine Rollen, keine Nutzertrennung und keine Prüfung, wem ein Job oder eine Datei gehört.

Der Medien-Endpunkt liefert einen übergebenen Dateipfad aus, sofern die Datei existiert. Er beschränkt sich nicht auf Projektmedien. Uploads und mehrere lokale Dateipfad-Eingaben haben ebenfalls keine gemeinsame Prüfung eines erlaubten Speicherbereichs. Vor einem späteren öffentlichen Betrieb müssten Zugriffsschutz und Dateigrenzen ausdrücklich umgesetzt werden. Eine eingeschränkte CORS-Liste ersetzt keine Anmeldung.

API-Schlüssel und Social-Tokens liegen lokal im Klartext. Die globale Konfiguration wird vollständig an den Browser übertragen. Das ist für die eigene lokale Sitzung nachvollziehbar, aber kein geeignetes Mehrbenutzermodell. Fehlermeldungen und Anbieterantworten können ebenfalls Details enthalten, die bei öffentlichem Betrieb nicht jedem Besucher angezeigt werden sollten.

Abbruch ist ein weiteres Thema: Die Quick-Pipeline prüft ein Stoppsignal zwischen Schritten. Nicht jede Pipeline liest das Signal, und ein laufender FFmpeg-Prozess oder Anbieteraufruf wird damit nicht durchgehend sofort beendet. `stop_job()` setzt zudem den Zustand vor dem Update auf „cancelled“, sodass die Zustandsänderung dort unter Umständen nicht mehr ausgesendet wird.

Python-Abhängigkeiten sind weitgehend ohne Versionsbindung eingetragen. Für den untersuchten lokalen Lauf wurden sie installiert; ein neuer Installationszeitpunkt kann andere Versionen auflösen. Das Google-SDK meldete beim lokalen Start eine Deprecation-Warnung. Automatisierte Projekttests und eine CI-Konfiguration sind im untersuchten Repositorybestand nicht vorhanden. Die vorangegangenen Prüfungen waren direkte lokale Tests.

Quellen: [server/routers/generation.py:240](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:240), [server/routers/clipper.py:56](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/clipper.py:56), [server/main.py:29](/home/dragos/orca/workspaces/Medienwerk/darter/server/main.py:29), [config.py:94](/home/dragos/orca/workspaces/Medienwerk/darter/config.py:94), [server/core/queue.py:173](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/queue.py:173), [pipeline.py:221](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:221), [requirements.txt:1](/home/dragos/orca/workspaces/Medienwerk/darter/requirements.txt:1), [api_clients.py:17](/home/dragos/orca/workspaces/Medienwerk/darter/api_clients.py:17).

## 13. Die wichtigsten Befunde für die Weiterentwicklung

| ID | Auswirkung | Befund | Ansatzpunkt |
| --- | --- | --- | --- |
| F01 | Ergebnisse fehlen | Quick Creator, Director, VideoFX und Agenten passen nicht zur Historie. | Gemeinsames Projekt- und Ausgabemodell. |
| F02 | Anbieter funktioniert trotz Schlüssel nicht | Unterschiedliche WaveSpeed-Schlüsselnamen. | Konfigurationsschema vereinheitlichen. |
| F03 | Kampagnenproduktion scheitert | `TrendAgent.google_client` existiert nicht. | Scheduler an einen vorhandenen Textclient anbinden. |
| F04 | Sprachfunktion scheitert | `generate_speech()` fehlt im WaveSpeed-Client. | Auf vorhandene TTS-Methode abstimmen. |
| F05 | Oberfläche zeigt unechte Daten | Dashboard-Zahlen, letzte Projekte und API-Status sind statisch. | Echte Projektdaten und Zustandsprüfung. |
| F06 | Schnittbedienung wirkungslos | Timeline-Vorschau und Griffe sind nicht an Video/Bedienung gebunden. | Tatsächlichen Clip-Editor implementieren. |
| F07 | Social-Status irreführend | Simulierte Tokens und echter Upload sind getrennt. | Ein klarer, echter Anmelde- und Veröffentlichungsweg. |
| F08 | Alte Inhalte bei neuen Optionen | Wiederverwendung nur nach Thema, URL und Dateiexistenz. | Eingaben und Einstellungen versionieren. |
| F09 | Fortschritt und Abbruch unzuverlässig | Unterschiedliche Nachrichtenformate, Schritt-/Gesamtfortschritt und Abbruchlogik. | Einheitlicher Job-Vertrag. |
| F10 | Sprach-/Formatwahl wirkt unterschiedlich | Englisch im Clipper; Tool-Format 1:1 wird nicht separat verarbeitet; Aspect-Strings uneinheitlich. | Typisierte, modulübergreifende Optionen. |
| F11 | Brand-Seite unbenutzbar | Backend und Quick-Branding vorhanden, Oberfläche Platzhalter. | Upload- und Vorschauoberfläche ergänzen. |
| F12 | Agentenablauf unvollständig verbunden | Platzhalterseite, Storyboard-Dateipfad statt Szenenliste, Rendering ohne Jobmodell. | Einen durchgängigen Studioprozess herstellen. |
| F13 | Schalter ohne vollständigen Effekt | Omnichannel, Stil und weitere Einstellungen nicht durchgängig ausgewertet. | Jede Option mit ihrer tatsächlichen Verarbeitung abgleichen. |
| F14 | Neustart verliert Auftragszustand | Jobs nur im RAM; Ergebnisse bleiben als Dateien. | Dauerhafte Jobs, Wiederaufnahme und Bereinigung. |
| F15 | Öffentlicher Betrieb wäre ungeschützt | Keine Anmeldung oder gemeinsamen Grenzen für Dateizugriffe. | Vor späterem Onlinebetrieb Zugriffsmodell festlegen. |

Die Tabelle beschreibt die Priorität aus technischer Sicht. Welche Punkte zuerst bearbeitet werden, hängt davon ab, welchen Produktionsablauf du zuerst wirklich nutzen möchtest.

## 14. Wo wir Anpassungen am sinnvollsten ansetzen

### Name, Design und deutsche Oberfläche

Hier beginnen wir bei `layout.tsx`, `Sidebar.tsx`, `globals.css` und den Seitentexten. Eine zentrale Übersetzungsstruktur und gemeinsame UI-Komponenten würden spätere Änderungen vereinfachen. Diese Arbeiten beeinflussen die Produktionslogik wenig, solange API-Verträge gleich bleiben. Modellprompts und erzeugte Inhalte brauchen zusätzlich eine separate Spracheinstellung.

### Ein verlässlicher Hauptablauf

Für deinen ersten wirklich nutzbaren Medienwerk-Ablauf würde ich einen Weg auswählen, etwa vorhandenes Video → deutschsprachige Shorts oder Thema → fertiges Video. Dann verbinden wir Eingaben, validierte Einstellungen, Aufträge, Ausgabe und Historie durchgängig. So lässt sich ein vollständiger Fall beurteilen, bevor wir weitere Funktionen ausbauen.

### Einstellungen und KI-Anbieter

Eine gemeinsame Provider-Schnittstelle mit klar getrennten Fähigkeiten für Text, Audio, Bild und Video würde neue Anbieter erleichtern. Dabei müssen nicht sofort alle Clients neu geschrieben werden. Als erster Schritt reichen ein eindeutiges Konfigurationsschema und Adapter um die vorhandenen Methoden. Anbieterfehler sollten verständlich angezeigt werden; ausgewählte Modelle und notwendige Schlüssel sollten vor dem Auftrag geprüft werden.

### Projekte und Hintergrundarbeit

Ein gemeinsames Register für Projekte, Medien und Jobs sollte die Ordnersuche ablösen. Für den lokalen Betrieb kann die vorhandene SQLite-Technik dafür erweitert werden. Das erfordert noch keinen Wechsel auf eine externe Datenbank. Produktion, Historie, Dashboard und Publish würden dadurch dieselben Daten verwenden. Entscheidungen über Cloudspeicher oder verteilte Worker können wir treffen, wenn ein entsprechender Bedarf entsteht.

### Eigene Änderungen und Original-Updates

`origin` ist dein Fork und `upstream` das Original. Eigene Funktionen sollten in überschaubaren Commits und möglichst klaren neuen Modulen entstehen. Anpassungen in den großen Dateien `pipeline.py` und `api_clients.py` erhöhen die Wahrscheinlichkeit von Konflikten mit Original-Updates. Kleine Adapter und zentrale Datenmodelle können diese Eingriffspunkte reduzieren; konfliktfreie Updates sind trotzdem nicht garantiert.

Für neue Projekte und Jobs empfehle ich eine eigene Schicht, auf die bestehende Pipelines schrittweise umgestellt werden. Das ist eine Empfehlung zur Struktur, keine bereits umgesetzte Änderung. Der vorhandene Merge-Ablauf steht in `UPSTREAM.md`.

Quellen: [web/src/app/globals.css:1](/home/dragos/orca/workspaces/Medienwerk/darter/web/src/app/globals.css:1), [server/core/database.py:1](/home/dragos/orca/workspaces/Medienwerk/darter/server/core/database.py:1), [api_clients.py:171](/home/dragos/orca/workspaces/Medienwerk/darter/api_clients.py:171), [pipeline.py:205](/home/dragos/orca/workspaces/Medienwerk/darter/pipeline.py:205), [UPSTREAM.md:1](/home/dragos/orca/workspaces/Medienwerk/darter/UPSTREAM.md:1).

## 15. Ausgangspunkt für unsere nächste Entscheidung

Die technische Struktur ist jetzt nachvollziehbar. Für die eigentliche Anpassung brauchen wir vor allem dein gewünschtes Ergebnis: Welche Inhalte möchtest du produzieren, welcher Ablauf soll zuerst vollständig funktionieren, welche Anbieter möchtest du nutzen und wie viel Kontrolle brauchst du vor dem Rendern?

Meine erste technische Empfehlung ist ein gemeinsames Projektmodell plus konsistente Einstellungen, verbunden mit einem ausgewählten Hauptablauf. Name, Sprache und Design können wir darauf abgestimmt ändern. Die beschriebenen Befunde bleiben als Arbeitsgrundlage im Repository; die visuelle Ausgabe erlaubt das Kommentieren konkreter Module und Aussagen.

## 16. Anhang: Schnittstellen im aktuellen Code

Diese Liste wurde aus den Router-Dekoratoren im untersuchten Arbeitsstand abgeleitet. Sie zeigt vorhandene Schnittstellen, keine Bestätigung erfolgreicher Verarbeitung. Die interaktive FastAPI-Dokumentation liegt lokal unter [localhost:8008/docs](http://localhost:8008/docs). Zusätzlich definiert `server/main.py` die Endpunkte `GET /health`, `GET /api/config` und `POST /api/config`.

| Methode | Adresse | Implementierung |
| --- | --- | --- |
| POST | `/api/generate/quick` | [generation.py:100](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:100) |
| WEBSOCKET | `/api/generate/ws/{job_id}` | [generation.py:106](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:106) |
| GET | `/api/generate/viral-topics` | [generation.py:117](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:117) |
| GET | `/api/generate/status/{job_id}` | [generation.py:124](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:124) |
| POST | `/api/generate/cancel/{job_id}` | [generation.py:131](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:131) |
| GET | `/api/generate/settings` | [generation.py:136](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:136) |
| POST | `/api/generate/settings` | [generation.py:140](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:140) |
| GET | `/api/generate/history` | [generation.py:147](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:147) |
| DELETE | `/api/generate/history/{project_id}` | [generation.py:227](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:227) |
| GET | `/api/generate/media` | [generation.py:240](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/generation.py:240) |
| POST | `/api/clipper/analyze` | [clipper.py:30](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/clipper.py:30) |
| POST | `/api/clipper/analyze_local` | [clipper.py:56](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/clipper.py:56) |
| POST | `/api/clipper/render` | [clipper.py:91](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/clipper.py:91) |
| POST | `/api/videofx/generate` | [videofx.py:51](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/videofx.py:51) |
| DELETE | `/api/videofx/job/{job_id}` | [videofx.py:57](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/videofx.py:57) |
| POST | `/api/videofx/login` | [videofx.py:62](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/videofx.py:62) |
| WEBSOCKET | `/api/videofx/ws/{job_id}` | [videofx.py:80](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/videofx.py:80) |
| POST | `/api/director/process` | [director.py:39](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/director.py:39) |
| POST | `/api/explainer/process` | [explainer.py:53](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/explainer.py:53) |
| POST | `/api/brand/upload` | [brand.py:11](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/brand.py:11) |
| DELETE | `/api/brand/delete/{type}` | [brand.py:36](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/brand.py:36) |
| POST | `/api/tools/caption` | [tools.py:17](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/tools.py:17) |
| POST | `/api/tools/convert` | [tools.py:55](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/tools.py:55) |
| POST | `/api/tools/tts` | [tools.py:92](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/tools.py:92) |
| GET | `/api/publish/library` | [publish.py:18](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/publish.py:18) |
| POST | `/api/publish/youtube` | [publish.py:82](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/publish.py:82) |
| POST | `/api/studio/chat` | [studio.py:41](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:41) |
| POST | `/api/studio/script` | [studio.py:89](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:89) |
| POST | `/api/studio/storyboard` | [studio.py:107](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:107) |
| POST | `/api/studio/render` | [studio.py:158](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/studio.py:158) |
| GET | `/api/campaigns/` | [campaigns.py:16](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/campaigns.py:16) |
| POST | `/api/campaigns/` | [campaigns.py:20](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/campaigns.py:20) |
| POST | `/api/campaigns/{cid}/toggle` | [campaigns.py:28](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/campaigns.py:28) |
| DELETE | `/api/campaigns/{cid}` | [campaigns.py:35](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/campaigns.py:35) |
| GET | `/api/social/status` | [social.py:16](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:16) |
| GET | `/api/social/youtube/auth` | [social.py:28](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:28) |
| POST | `/api/social/youtube/callback` | [social.py:34](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:34) |
| POST | `/api/social/tiktok/auth` | [social.py:51](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:51) |
| POST | `/api/social/instagram/auth` | [social.py:55](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:55) |
| POST | `/api/social/publish/youtube` | [social.py:59](/home/dragos/orca/workspaces/Medienwerk/darter/server/routers/social.py:59) |
