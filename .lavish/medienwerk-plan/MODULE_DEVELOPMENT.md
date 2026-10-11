# Verträge für neue Medienwerk-Module

Diese Anleitung beschreibt die lokale Projekt-, Auftrags- und Medienbasis für
spätere Anpassungen. Sie ergänzt die historische [Plattformanalyse](PLATFORM_ANALYSIS.md)
und den [Stabilisierungsbericht](STABILIZATION_RESULT.md); sie ersetzt keine
Anbieter- oder Browserprüfung.

## Verbindlicher Ablauf

1. **Einstellungen lesen:** `effective_config(overrides)` erzeugt die wirksame
   Konfiguration für einen neuen Auftrag. Sie enthält intern nötige Schlüssel.
   Vor einem Anbieteraufruf `validate_provider_config(config, kind=...)`
   aufrufen. Für API-Antworten `public_config()` und für gespeicherte Jobwerte
   `sanitize_config()` verwenden.
2. **Projekt und Job erstellen:** Einen stabilen `workflow`-Namen verwenden und
   `create_job(topic, project_id=None, workflow=..., settings=..., idempotency_key=...)`
   aufrufen. Das Job-Snapshot enthält keine Geheimnisse. Bei einem bewussten
   erneuten Quick-Creator-Versuch dieselbe Projekt-ID mit einer neuen Job-ID
   verwenden; ein aktives Projekt ist nicht wiederverwendbar. Derselbe
   Idempotency-Key für denselben Workflow gibt bei identischem Request den bereits
   erstellten Job zurück; abweichende Quick-Creator-Requests und Tools-Optionen
   werden mit HTTP 409 abgewiesen.
3. **Einmalig beanspruchen:** Der Worker-Pool übergibt die Job-ID an
   `claim_job()`. Nur ein erfolgreicher Claim darf die Arbeit ausführen. Neue
   Produktionsjobs werden nicht bei Prozessstart automatisch erneut eingereiht.
4. **Dateien isolieren:** Projektdateien liegen unter
   `workspace/projects/<project-uuid>/source`, `intermediate` oder `output`.
   Zwischenstände eines Versuchs erhalten eine Job-ID als Unterordner. Für neue
   Medien keine nutzerkontrollierten Pfadsegmente verwenden.
5. **Abbruch beachten:** `get_stop_event(job_id)` an den Prozessrunner und
   unterstützte Providerclients weiterreichen. Lokale Unterprozesse gezielt
   beenden. Lange Wartezeiten mit `stop_event.wait(seconds)` implementieren.
   Ein Abbruch gilt erst als bestätigt, wenn der lokale Worker beendet oder ein
   wartender Auftrag sicher abgebrochen ist. Externe Anbieter können weiterlaufen.
6. **Fortschritt melden:** Stabile Schritt-IDs mit `update_step()` aktualisieren.
   Bei fester Schrittfolge `total_steps` übergeben, damit noch ausstehende
   Schritte beim Gesamtfortschritt mitzählen. Optionale übersprungene Schritte
   kenntlich machen. Geheimnisse, vollständige
   Konfigurationsobjekte und rohe Anbieterantworten gehören weder in Logs noch in
   Events.
7. **Ausgabe prüfen und abschließen:** Vor Abschluss Datei, Medientyp,
   Audio-/Videostreams und Pfad prüfen. Dann `complete_job(job_id, result=...,`
   `media_records=[{"path": ..., "role": "final", "kind": "video"}])`
   verwenden. Medienregistrierung und Jobabschluss werden gemeinsam gespeichert.
   Ein Erfolg darf nicht gemeldet werden, bevor eine echte Enddatei registriert ist.
8. **Fehler sichtbar machen:** Pflichtschritte beenden den Job mit `failed`.
   Optionale Fehler kommen als bereinigte Warnungen ins Ergebnis. Keine
   unmarkierte Ersatzdatei oder schwarze Platzhalterausgabe als Erfolg werten.

## Gemeinsame Zustände und Ressourcen

Auftragszustände sind `queued`, `running`, `awaiting_input`, `cancel_requested`,
`completed`, `failed`, `cancelled` und `interrupted`. Status und Ereignisse sind
SQLite-gestützt; WebSocket-Nachrichten sind eine Echtzeitansicht. Clients müssen
den aktuellen Status auch per HTTP lesen können, wenn sie Events verpasst haben.

Der zentrale Worker-Pool ist auf zwei parallele Jobs und eine begrenzte
Einreihung ausgelegt. Er ist lokal und pro Prozess; es gibt keine verteilte
Worker- oder Scheduler-Sperre. Kampagnen verwenden persistente Fälligkeits-
Idempotenz im lokalen SQLite-Auftragsbestand.

Medien werden über IDs aus `server.core.media_store` aufgelöst. Ein absoluter
Dateipfad ist kein API-Medienbezeichner. Importierte Altmedien müssen aus einem
ausdrücklich gewählten Wurzelordner registriert werden; normale Projektlöschung
entfernt importierte Originaldateien nicht.

Konfigurationsantworten zeigen Schlüsselnamen und Status, nicht Werte. Ein
leeres Feld ersetzt oder löscht gespeicherte Schlüssel nicht. Ersatz und Löschung
werden über `replace_secrets` beziehungsweise `delete_secrets` ausdrücklich
angefordert.

## Vorlage für ein neues Modul

- Eigener Router- und Engine-Bereich; keine zweite globale Queue, Projekt- oder
  Konfigurationsablage einführen.
- Ein Request-Schema begrenzt Text, IDs, Enumwerte, Zahlen und Uploadgrößen.
- Ein Startdienst validiert und friert Einstellungen ein, erstellt Projekt/Job
  und gibt `{job_id, project_id, status}` zurück.
- Der Worker schreibt in einen Job-eigenen Ordner, aktualisiert Schritte,
  respektiert Stoppsignale und registriert geprüfte Ausgaben.
- GET-Status-/Eventantworten liefern dieselben dauerhaften IDs und Zustände.
- Tests verwenden pro Sitzung isolierte SQLite-, Workspace- und
  Konfigurationspfade. Providerantworten werden kontrolliert simuliert; ein Test
  darf nicht durch unbeabsichtigte Netzaufrufe oder Veröffentlichungen Geld
  ausgeben oder externe Inhalte verändern.

Vor einer neuen Umsetzung [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) und den
relevanten Abschnitt des [Stabilisierungsplans](STABILIZATION_PLAN.md) lesen.
