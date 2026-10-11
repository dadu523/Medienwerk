# Medienwerk: Subagents, Skills und abschließende Prüfung

Stand: 11. Oktober 2026. Grundlage sind der [Stabilisierungsplan](STABILIZATION_PLAN.md), der vorhandene Skillbestand und die Recherche in den Originalrepositories. Dieser Workflow wird für die beauftragte Stabilisierung verwendet. Den umgesetzten Stand und die lokale Abnahme dokumentiert [STABILIZATION_RESULT.md](STABILIZATION_RESULT.md).

## 1. Vereinbarte Rollen

**Ausführung:** Subagents mit `gpt-6-luna`, Reasoning `high`. **Koordination und abschließende Prüfung:** der Hauptagent. Die Modellauswahl wurde in dieser Recherche bereits für zwei Subagents verwendet; beide lieferten ihre Prüfungsergebnisse zurück.

Der Hauptagent legt Schnittstellen, Reihenfolge und Dateizuständigkeiten fest. Danach übernehmen die Subagents abgegrenzte Aufgaben. Vor Abschluss liest der Hauptagent die relevanten Änderungen selbst, prüft ihre gemeinsame Wirkung und gleicht sie mit den Abschlusskriterien ab. Die abschließende Prüfung wird nicht allein an einen weiteren Subagent ausgelagert.

Bei der aktuellen Kapazität sind maximal drei Worker gleichzeitig neben dem Hauptagent möglich. Das ist eine Obergrenze; gemeinsame Einstellungen, Migrationen und Job-Verträge werden schrittweise umgesetzt. Parallelität hilft vor allem bei unabhängiger Recherche, getrennten Adaptern und voneinander getrennten Oberflächenbereichen.

## 2. Aufgabenteilung für P0–P6

| Etappe | Aufgabe für Luna/high | Aufgabe des Hauptagenten |
| --- | --- | --- |
| P0 | Arbeitsstand, Ausschlüsse und reproduzierbare Installation vorbereiten; Daten-/Sicherungsbedarf erfassen. | Ausgangsstand und Wiederherstellungsweg prüfen; Zuständigkeiten für Sicherungen und Laufzeitdaten festlegen. |
| P1 | Konfigurationsschema, Aliase und Adapter implementieren; getrennte Formularanpassung erst nach festem API-Vertrag. | Schlüsselerhalt, wirksame Optionen, Secrets-Rückgabe und Kompatibilität überprüfen. |
| P2 | Ein Worker für Datenmodell/Migrationsserie; anschließend ein Worker für Import-/Mediendienste. | Migration und Altimport auf Datenverlust, Wiederholbarkeit und Pfadgrenzen prüfen. |
| P3 | Backend-Jobvertrag zuerst; Frontend-Client anschließend anhand dieses Vertrags. | Zustandsübergänge, Neustart, Abbruch, frühe Abschlüsse und doppelte Starts prüfen. |
| P4 | Quick Creator zuerst; weitere Adapter bei getrennten Dateien danach parallel möglich. | Endausgaben, Projektzuordnung und Kompatibilität jedes Adapters prüfen. |
| P5 | History/Publish und Dashboard/Sidebar als getrennte Pakete nach gemeinsamem Datenvertrag. | Konsistenz des Bestands sowie echte Status- und Leeranzeigen prüfen. |
| P6 | Für beauftragte Prüfungen: klar begrenzte Backend-, Medien- und Browserfälle vorbereiten/durchführen. | Gesamtergebnis selbst beurteilen, offene Fälle dokumentieren und Abschlussbericht erstellen. |

**Dateizuständigkeit:** Ein Dateibereich hat genau einen schreibenden Agenten. Die zentralen Dateien `config.py`, `server/core/database.py`, `server/core/queue.py`, `pipeline.py` und `api_clients.py` werden nicht gleichzeitig von mehreren Workern bearbeitet. Ein Frontend-Worker implementiert gegen einen vereinbarten Vertrag, nicht gegen Vermutungen über den gerade entstehenden Backend-Code.

**Worktrees:** Für größere unabhängige Pakete erhält jeder schreibende Worker einen eigenen Branch/Worktree, der vom gesicherten angepassten Stand stammt. Das aktuelle Verzeichnis enthält noch lokale Änderungen; neue Worktrees können diese nicht automatisch aus `HEAD` übernehmen. Daher wird die Basis zuerst in P0 bewusst hergestellt. Worktrees teilen keine produktive SQLite-Datei, Outputordner, Browserprofile oder Standardports. Secrets werden nicht automatisch kopiert. Kleine getrennte Änderungen können im gemeinsamen Verzeichnis erfolgen, wenn die Dateizuständigkeit eindeutig ist.

## 3. Was jeder Auftrag enthalten muss

Ein Auftrag enthält folgende Angaben:

1. Aufgaben-ID und ein konkretes Ergebnis, beispielsweise „Konfigurationsalias ohne Schlüsselverlust normalisieren“.
2. Erlaubte Dateien und ausdrücklich bekannte gemeinsame Schnittstellen.
3. Vorherige Ergebnisse, notwendige Typen/Schemas sowie den relevanten Abschnitt des Stabilisierungsplans.
4. Abschlusskriterien, erwartete Fehlerfälle und die erlaubten Prüfungen.
5. Ausgewählte Skills mit konkreten Pfaden; zuerst ihre Anwendbarkeit prüfen.
6. Ausgabeformat: geänderte Dateien, Begründung, Vertragseinfluss, tatsächlich ausgeführte Prüfungen, offene Fälle, Rückweg.
7. Modell `gpt-6-luna`, Reasoning `high`, begrenzter Scope und keine weitere Delegation ohne Auftrag des Hauptagenten.

Bei einer fehlerhaften Übergabe erhält der Worker einen konkreten Korrekturauftrag. Nach zwei erfolglosen Korrekturen zerlegt der Hauptagent die Ursache neu und passt den Auftrag an. Gemeinsame Verträge dürfen nicht zur Umgehung eines Fehlers eigenmächtig geändert werden.

## 4. Vorhandene passende Skills

Die folgenden Skills sind im bereitgestellten Sitzungskatalog vorhanden. Die Auswahl wurde anhand der Beschreibungen und einschlägigen Anleitungen geprüft. Vor ihrem konkreten Einsatz wird jeweils die vollständige Anleitung gelesen.

| Skill | Verwendung | Grenze |
| --- | --- | --- |
| [agent-workflow-designer](/home/dragos/.agents/skills/agent-workflow-designer/SKILL.md) | Hauptagent: Aufteilung, Abhängigkeiten und Übergaben. | Kleine Aufgaben nicht unnötig parallelisieren; kein zusätzliches Agentenframework nötig. |
| [git-worktree-manager](/home/dragos/.agents/skills/git-worktree-manager/SKILL.md) | P0 und unabhängige Änderungspakete isolieren. | Scripts können Umgebungsdateien kopieren oder Dependencies installieren; diese Optionen gezielt behandeln. |
| [env-secrets-manager](/home/dragos/.agents/skills/env-secrets-manager/SKILL.md) | P0/P1: Git-Ausschlüsse und Umgang mit Schlüsseln. | Cloud-Secrets und Schlüsselrotation sind keine Voraussetzung dieses lokalen Plans. |
| [database-schema-designer](/home/dragos/.agents/skills/database-schema-designer/SKILL.md) | P2: Entitäten, Beziehungen und Migrationen. | PostgreSQL-/RLS-Beispiele nicht auf den lokalen SQLite-Betrieb übertragen. |
| [migration-architect](/home/dragos/.agents/skills/migration-architect/SKILL.md) | P2/P3: Planung von Übernahme und Rückweg. | Nur das lokale Migrationsproblem bearbeiten; kein Infrastrukturwechsel. |
| [code-reviewer](/home/dragos/.agents/skills/code-reviewer/SKILL.md) | Hauptagent: Prüfung konkreter Python-/TypeScript-Änderungen. | Passende Sprachregeln und universelle Regeln laden; Skriptergebnis ersetzt keine Integrationsprüfung. |
| [pr-review-expert](/home/dragos/.agents/skills/pr-review-expert/SKILL.md) | Später für einen tatsächlich vorhandenen PR. | Externe Kommentare, Ticketaktionen und PR-Änderungen gehören nur in einen entsprechenden Auftrag. |
| [playwright-pro](/home/dragos/.agents/skills/playwright-pro/SKILL.md) | P6 bei beauftragten Browser-/E2E-Prüfungen. | Keine TestRail-/BrowserStack-Dienste oder neue Testinstallation als automatische Voraussetzung. |

Zusätzlich liegt [sql-database-assistant](/home/dragos/.agents/skills/sql-database-assistant/SKILL.md) auf dem Dateisystem. Seine Beschreibung und einschlägigen Abschnitte behandeln SQLAlchemy, SQLite und Alembic. Er ist in dem für diese Sitzung bereitgestellten Skillkatalog nicht aufgeführt; Dateivorkommen und automatische Verfügbarkeit sind daher getrennt zu betrachten. Er kann nach gezieltem vollständigem Lesen eine vorhandene Ergänzung sein.

`focused-fix` ist für einzelne durchgängige Reparaturen interessant, verlangt aber Tests und weitere `superpowers`-Skills. Vor Verwendung müssen deren Verfügbarkeit und der Prüfauftrag passen. `spawn` ist ein AgentHub-Wettbewerbsworkflow; `agent-launcher-orchestrator` richtet sich an Claude Managed Agents; `agent-protocol` an C-Suite-Rollen. Diese Fähigkeiten passen nicht als allgemeiner Starter für unsere nativen Subagents. `no-mistakes` bringt einen umfangreichen Commit-/Push-/PR-Ablauf mit; er wird nicht zum Standard für die lokal geplante Runde.

## 5. Geprüfte GitHub-Ergänzungen

**Status:** Die vier empfohlenen Skills `vercel-react-best-practices`, `vercel-composition-patterns`, `python-background-jobs` und `python-testing-patterns` wurden gezielt installiert. Die geprüften Commit-Refs stehen in [STABILIZATION_PROGRESS.md](STABILIZATION_PROGRESS.md). `fastapi-templates` und `alembic` wurden nicht installiert. Die Empfehlungen beruhen auf Original-Skilldateien. Die Nutzung setzt ein gezieltes Lesen der jeweiligen Regeln/Referenzen voraus; Beispielcode muss mit den lokalen Paketversionen vereinbar sein.

| Kandidat | Nutzen für Medienwerk | Bewertung und Quelle |
| --- | --- | --- |
| `vercel-react-best-practices` | P5: Datenladen, Effects, Aktualisierungen und gemeinsamer Job-Client. | Empfohlene Ergänzung aus Vercels Sammlung. Keine zusätzlichen State-/Cache-Bibliotheken nur wegen eines Beispiels einführen. [Original](https://github.com/vercel-labs/agent-skills/blob/main/skills/react-best-practices/SKILL.md). |
| `vercel-composition-patterns` | P5: gemeinsame Status-/Ergebnis-Komponenten und Context-Grenzen. | Bei tatsächlichem Komponentenrefactoring einsetzen. Enthält React-19-Hinweise; das passt zur installierten Hauptversion. [Original](https://github.com/vercel-labs/agent-skills/blob/main/skills/composition-patterns/SKILL.md). |
| `python-background-jobs` | P3: dauerhafte Zustände, doppelte Starts und Idempotenz. | Empfohlene Musterhilfe. Celery/Redis-Beispiele werden nicht zur Architekturvorgabe; wir bleiben bei Threadpool und SQLite. Automatische Wiederholungen dürfen keine unbeabsichtigten Anbieteraufrufe auslösen. [Original](https://github.com/wshobson/agents/blob/main/plugins/python-development/skills/python-background-jobs/SKILL.md). |
| `python-testing-patterns` | Spätere beauftragte Backend-Abnahme: pytest, Fixtures, Anbieter-Mocks, Fehler-/Neustartfälle. | Gute Ergänzung für konkrete Prüfaufträge. Kein Anlass, bei der Skillrecherche Tests anzulegen. [Original](https://github.com/wshobson/agents/blob/main/plugins/python-development/skills/python-testing-patterns/SKILL.md). |
| `fastapi-templates` | P1/P3: Schema-, Service- und Dependency-Injection-Muster. | Bedingt nützlich: hauptsächlich für neue Projekte und Async-Stacks. Vorhandenen Monolith nicht neu scaffolden. [Original](https://github.com/wshobson/agents/blob/main/plugins/api-scaffolding/skills/fastapi-templates/SKILL.md). |
| `alembic` von bm629 | P2: bestehende `create_all`-Datenbank übernehmen, Migrationen prüfen und SQLite-Batch-Verfahren berücksichtigen. | Spezifisch passend, aber kleines Repository mit nur drei Sternen bei der Prüfung. Daher Zusatzreferenz, keine ungeprüfte Standardautomatisierung. [Original](https://github.com/bm629/agent-skills/blob/main/skills/alembic/SKILL.md). |

Der allgemeine [`database-migration`](https://github.com/wshobson/agents/blob/main/plugins/framework-migration/skills/database-migration/SKILL.md)-Skill von wshobson hat überwiegend Beispiele für Sequelize, TypeORM und Prisma. Für unsere SQLAlchemy-Migration ist seine konkrete Anleitung weniger passend.

[`next-best-practices` wurde als separater Skill eingestellt](https://github.com/vercel-labs/next-skills/blob/main/README.md). Next.js liefert die Referenzdokumentation inzwischen mit der Framework-Version aus. Medienwerks `web/AGENTS.md` verweist bereits auf `web/node_modules/next/dist/docs/`; diese Quelle hat für Next-spezifische Arbeit Vorrang.

OpenAIs [`playwright`](https://github.com/openai/skills/blob/main/skills/.curated/playwright/SKILL.md) ist eine weitere CLI-Browserhilfe, überschneidet sich hier aber mit dem vorhandenen Chrome-Wrapper. [`playwright-interactive`](https://github.com/openai/skills/blob/main/skills/.curated/playwright-interactive/SKILL.md) verlangt `js_repl`, das in der aktuellen Toolliste fehlt. Deshalb empfiehlt die Recherche keinen Wechsel zu diesem Workflow.

### Herkunft und Verbreitung

Direkt über `gh-axi repo view` geprüft: `vercel-labs/agent-skills` 32.194 Sterne, `wshobson/agents` 40.366 Sterne, `openai/skills` 27.988 Sterne und `bm629/agent-skills` 3 Sterne. Diese Zahlen sind eine Momentaufnahme und kein Funktionsnachweis.

Das [Skills-Verzeichnis für React](https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices) zeigt ungefähr 787.000 Installationen, [Composition](https://skills.sh/vercel-labs/agent-skills/vercel-composition-patterns) ungefähr 385.000, [Python Jobs](https://skills.sh/wshobson/agents/python-background-jobs) ungefähr 10.600 und [Python Testing](https://skills.sh/wshobson/agents/python-testing-patterns) ungefähr 35.100. Verzeichnis und CLI können leicht unterschiedliche Stände zeigen; die inhaltliche Prüfung ist entscheidend.

### Gezielte Installation

Bei weiteren beauftragten Installationen einzelne Skills über den vorhandenen `skill-installer` aus genau dem geprüften Repositorypfad übernehmen. Vorher einen konkreten Git-Ref festhalten, vorhandene gleichnamige Ordner prüfen und notwendige Referenzdateien mit einbeziehen. Keine vollständigen Skillpakete und keine pauschalen Updates aller vorhandenen Skills.

Beispielaufrufe für gezielte Installation mit dem offiziellen Helper (Platzhalter-Ref vor Ausführung ersetzen):

```bash
python3 /home/dragos/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo vercel-labs/agent-skills --path skills/react-best-practices --name vercel-react-best-practices --ref GEPRUEFTER_COMMIT_SHA
python3 /home/dragos/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo wshobson/agents --path plugins/python-development/skills/python-background-jobs --ref GEPRUEFTER_COMMIT_SHA
```

Der vollständige lokale Dateibestand ist in [SKILLS_INVENTORY.csv](SKILLS_INVENTORY.csv) festgehalten. Gefunden wurden 451 `SKILL.md`-Dateien in drei geprüften Wurzelverzeichnissen, einschließlich Plugin-Versionen und einer Beispielskilldatei. Das sind nicht 451 eindeutige oder automatisch aktivierte Skills.

## 6. Abschließende Prüfung durch den Hauptagenten

Der Hauptagent prüft jedes übergebene Änderungspaket selbst auf Scope und Vertragseinfluss. Vor dem Gesamtabschluss werden mindestens folgende Fragen anhand der Änderungen und der beauftragten Prüfungen beantwortet:

- Verwenden Formulare, Router und Worker dieselben Einstellungen und Datentypen?
- Bleiben alte Konfigurationen, Medien und OAuth-Daten bei Übernahme und Rückweg erhalten?
- Sind Projekte, Ergebnisse und Jobzustände konsistent; sind frühe Abschlüsse, Fehler und Unterbrechungen sichtbar?
- Können Doppelklick, Wiederverbindung oder Neustart ungewollte neue Produktionsaufrufe auslösen?
- Greifen Abbruch, Datei-Auslieferung und Löschung nur auf die vorgesehenen Prozesse/Medien zu?
- Sind unvollständige Funktionen gekennzeichnet, und sind angebliche Erfolge durch konkrete Ergebnisse belegt?
- Welche Prüfungen wurden wirklich ausgeführt, und welche Anbieter-/Medienwege bleiben ungeprüft?

Anwendungsprüfungen richten sich nach dem Umsetzungsauftrag. Die ursprüngliche Skillrecherche prüfte nur Skilldateien, Quellen und Workflow-Regeln. Im danach beauftragten Umsetzungslauf hat der Hauptagent 96 Backend-Tests in zwei Umgebungen, einen vollständigen Frontend-Build sowie lokale Browser-/FFmpeg- und Neustartfälle geprüft. Nachweise und externe Prüfgrenzen stehen in [STABILIZATION_RESULT.md](STABILIZATION_RESULT.md).
