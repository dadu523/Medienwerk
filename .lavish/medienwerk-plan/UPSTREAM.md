# Medienwerk entwickeln und Updates übernehmen

Medienwerk wird im eigenen Repository weiterentwickelt. Die Git-Historie des
Originalprojekts bleibt erhalten, damit neue Änderungen zusammengeführt werden
können.

| Remote | Repository | Zweck |
| --- | --- | --- |
| `origin` | https://github.com/dadu523/Medienwerk | Eigene Änderungen veröffentlichen |
| `upstream` | https://github.com/naqashafzal/AI-Content-Studio | Updates des Originalprojekts abrufen |

Die Remotes sind in diesem lokalen Klon eingerichtet. Das Standardziel für
Pushes ist `origin`. Bei einem neuen Klon müssen `upstream` und das Standardziel
erneut eingerichtet werden:

```bash
git remote add upstream https://github.com/naqashafzal/AI-Content-Studio.git
git config --local remote.pushDefault origin
```

## Eigene Anpassungen

Aktuell wird auf `dadu523/customize-ai-content-studio` gearbeitet. Änderungen
in kleinen, nachvollziehbaren Commits speichern und zu `origin` pushen.
Für weitere Funktionen jeweils einen eigenen Branch vom aktuellen Stand des
Forks erstellen:

```bash
git fetch origin
git switch -c feature/meine-anpassung origin/main
```

Nach dem Bearbeiten gezielt die gewünschten Dateien mit `git add` vormerken,
committen und den Branch veröffentlichen:

```bash
git commit -m "Beschreibe die Anpassung"
git push -u origin HEAD
```

Anschließend einen Pull Request im eigenen Repository nach `main` erstellen.
Dadurch enthält `origin/main` die übernommenen eigenen Anpassungen.

## Neue Updates prüfen

```bash
git fetch upstream
git log --oneline HEAD..upstream/main
git diff HEAD...upstream/main
```

Diese Befehle laden und zeigen Änderungen; die Arbeitsdateien werden dabei
nicht verändert. Eine leere Commit-Liste bedeutet, dass der aktuelle Branch
bereits alle Commits von `upstream/main` enthält.

## Updates in Medienwerk übernehmen

Zuerst mit `git status` prüfen, dass alle eigenen Änderungen gespeichert sind.
Dann einen separaten Branch vom aktuellen `origin/main` erstellen. Für jede
Update-Runde einen neuen Namen wählen:

```bash
git fetch origin
git fetch upstream
git switch -c update/upstream-YYYYMMDD origin/main
git merge --no-ff upstream/main
```

Der Merge führt eigene und neue ursprüngliche Änderungen zusammen. Wenn beide
dieselben Stellen verändert haben, meldet Git Konflikte. Die betroffenen Dateien
bearbeiten, die Konfliktmarkierungen entfernen, mit `git add` vormerken und den
Merge mit `git commit` abschließen. Mit `git merge --abort` kann ein noch nicht
abgeschlossener Merge abgebrochen werden.

Nach Prüfung der Änderungen und der betroffenen Funktionen:

```bash
git push -u origin HEAD
```

Einen Pull Request im eigenen Repository nach `main` erstellen und dort die
Updates übernehmen. Offene Feature-Branches anschließend mit dem neuen
`origin/main` zusammenführen.

## Besonderheit dieses Arbeitsverzeichnisses

Dieses Verzeichnis ist ein Git-Worktree. `main` ist bereits in
`/home/dragos/orca/Medienwerk` ausgecheckt. Die obigen Befehle erstellen neue
Branches direkt von `origin/main` und funktionieren deshalb auch hier.

Die Remote-Konfiguration gilt für die Worktrees desselben lokalen Repositorys;
sie wird durch einen Commit oder Push nicht auf andere Rechner übertragen.
