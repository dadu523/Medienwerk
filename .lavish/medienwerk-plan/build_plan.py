"""Render the plan using Medienwerk styles. Run: uv run --with markdown build_plan.py."""
from pathlib import Path
import html
import re
import shutil
import markdown

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ANALYSIS = ROOT / '.lavish/medienwerk-analyse'
DOC = ROOT / 'docs/STABILIZATION_PLAN.md'
text = DOC.read_text()
OUT.mkdir(exist_ok=True)
for source, name in [(DOC,'STABILIZATION_PLAN.md'),(ROOT/'docs/PLATFORM_ANALYSIS.md','PLATFORM_ANALYSIS.md'),(ROOT/'docs/AGENT_WORKFLOW.md','AGENT_WORKFLOW.md'),(ROOT/'docs/STABILIZATION_RESULT.md','STABILIZATION_RESULT.md'),(ROOT/'docs/GEMINI_SDK_MIGRATION.md','GEMINI_SDK_MIGRATION.md'),(ROOT/'docs/STABILIZATION_PROGRESS.md','STABILIZATION_PROGRESS.md'),(ROOT/'docs/MODULE_DEVELOPMENT.md','MODULE_DEVELOPMENT.md'),(ROOT/'LOCAL_TESTING.md','LOCAL_TESTING.md'),(ROOT/'docs/SKILLS_INVENTORY.csv','SKILLS_INVENTORY.csv'),(ROOT/'UPSTREAM.md','UPSTREAM.md'),(ANALYSIS/'outfit.woff2','outfit.woff2'),(ANALYSIS/'dashboard.png','dashboard.png')]:
    shutil.copyfile(source,OUT/name)

css = re.search(r'<style>(.*?)</style>',(ANALYSIS/'index.html').read_text(),re.S).group(1)
css += '''
.plan-note{padding:18px 22px;border-left:3px solid var(--accent);background:var(--soft);border-radius:0 12px 12px 0;font-size:15px;margin:26px 0;color:var(--muted)}
.plan-note strong{color:var(--text)}.target-card{padding:25px;border:1px solid var(--border-glass);border-radius:16px;background:var(--bg-glass);margin-bottom:32px}.target-card h3{margin-top:0}.target-card p{color:var(--muted)}.phase-status{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-left:auto;border:1px solid var(--border-glass);border-radius:20px;padding:5px 10px;white-space:nowrap}
.report-section .section-heading{align-items:center}.section-number{flex:0 0 auto;white-space:nowrap}.phase-caption{color:var(--muted);font-size:13px;margin-bottom:30px}.goal-check{border:1px solid var(--accent);border-radius:14px;padding:22px;background:var(--soft)}.goal-check p:last-child{margin-bottom:0}.current-shot{max-width:640px;margin:25px 0}.current-shot img{width:100%;height:auto;aspect-ratio:1440/1100;border:1px solid var(--border-glass)}.codefree-diagram text{font-family:Outfit,system-ui,sans-serif}.hero-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:24px}.hero-actions a{padding:9px 14px;border:1px solid var(--border-glass);border-radius:10px;text-decoration:none;font-size:14px}.hero-actions a:first-child{border-color:var(--accent)}
@media(max-width:650px){.phase-status{display:none}.report-section .section-heading{align-items:baseline}.target-card{padding:18px}.plan-note{padding:16px;font-size:14px}#section-11 th:first-child{width:30%}}
'''

def node(id,y,title,description,tone='normal'):
    return f'<g id="{id}"><title>{html.escape(title+": "+description)}</title><rect class="node {tone}" x="25" y="{y}" width="330" height="80" rx="14"/><text class="node-title" x="190" y="{y+32}" text-anchor="middle">{html.escape(title)}</text><text class="node-sub" x="190" y="{y+57}" text-anchor="middle">{html.escape(description)}</text></g>'

diagram='<svg class="diagram codefree-diagram" viewBox="0 0 380 650" role="img" aria-labelledby="target-title"><title id="target-title">Umgesetzte lokale Verbindung: Eingabe, feste Optionen, Projekt und Job, Medienbestand und vorhandene Seiten</title><defs><marker id="target-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="var(--accent)"/></marker></defs>'
for i,(title,description,tone) in enumerate([
    ('Deine Eingabe','Vorhandenes Formular im Browser','normal'),
    ('Feste Einstellungen','Schema + geprüfte Anbieteroptionen','normal'),
    ('Projekt + Auftrag','Eindeutige IDs · Zustände in SQLite','accent'),
    ('Medien erzeugen','Vorhandene Pipeline · registrierte Datei','normal'),
    ('Gemeinsamer Bestand','History · Dashboard · Publish-Bibliothek','accent')
]):
    y=10+i*128
    diagram+=node('target-'+str(i+1),y,title,description,tone)
    if i<4:
        diagram+=f'<g id="target-edge-{i+1}"><title>Nächster Schritt im lokalen Ablauf</title><path class="edge" d="M190 {y+80} L190 {y+121}" marker-end="url(#target-arrow)"/></g>'
diagram+='</svg>'

illustration='<div class="illustration" id="zielstruktur"><figure>'+diagram+'<figcaption>Lokal umgesetzte Struktur · externe Anbieterwege separat prüfen</figcaption></figure><div class="figure-text"><div class="eyebrow">Das gemeinsame Fundament</div><h3>Ein Ergebnis bleibt seinem Projekt zugeordnet.</h3><p>Ein Auftrag startet mit geprüften Optionen. Sein Zustand und seine Ausgaben landen im gemeinsamen Bestand. Die vorhandenen Seiten können dadurch dieselben Informationen verwenden.</p><ul><li><strong>Projekt:</strong> Was wird produziert, und welche Medien gehören dazu?</li><li><strong>Job:</strong> Was läuft gerade, was ist fertig, was wurde unterbrochen?</li><li><strong>Einstellungen:</strong> Welche Optionen gelten für genau diesen Versuch?</li></ul><p>Der Threadpool und die Videodateien bleiben lokal. SQLite speichert deren Metadaten und die Zustände.</p></div></div>'

parts=re.split(r'^## (\d+)\. (.+)$',text,flags=re.M)
sections=[]
nav=[]
for i in range(1,len(parts),3):
    num,title,body=int(parts[i]),parts[i+1],parts[i+2]
    body=body.replace('../UPSTREAM.md','UPSTREAM.md')
    rendered=markdown.markdown(body,extensions=['tables'])
    rendered=rendered.replace('<table>','<div class="table-wrap"><table>').replace('</table>','</table></div>')
    inserts=illustration if num==2 else ''
    if num==9:
        inserts='<figure class="current-shot"><a href="dashboard-current.png" target="_blank"><img src="dashboard-current.png" width="1440" height="1100" alt="Medienwerk-Dashboard nach Stabilisierung mit tatsächlichem leerem Projektbestand" loading="lazy"></a><figcaption>Geprüfter lokaler Zustand nach P5: Projekt- und Medienzahlen kommen aus SQLite. Der normale Bestand enthält keine synthetischen Testprojekte.</figcaption></figure>'
    if num==13:
        rendered='<div class="goal-check">'+rendered+'</div>'
    badge='<span class="phase-status">Lokal umgesetzt</span>' if 4<=num<=10 else ''
    sections.append(f'<section class="report-section" id="section-{num}"><div class="section-heading"><span class="section-number">{num:02}</span><h2>{html.escape(title)}</h2>{badge}</div>{inserts}{rendered}</section>')
    nav.append(f'<a href="#section-{num}"><span>{num:02}</span>{html.escape(title)}</a>')

script='''
const root=document.documentElement;
document.querySelector('#theme-toggle').addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='light'?'dark':'light';document.querySelector('#theme-toggle').textContent=root.dataset.theme==='light'?'Dunkel':'Hell'});
const observer=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting)document.querySelectorAll('.contents a').forEach(a=>a.classList.toggle('active',a.hash==='#'+e.target.id))}},{rootMargin:'-10% 0px -75% 0px'});
document.querySelectorAll('.report-section').forEach(s=>observer.observe(s));
'''

result='<!doctype html><html lang="de" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light"><title>Medienwerk · Stabilisierungsplan</title><style>'+css+'</style></head><body>'
result+='<header class="topbar"><a class="identity" href="#top"><span class="logo" aria-hidden="true">M</span>Medienwerk <span style="color:var(--muted);font-weight:400">/ Plan</span></a><div class="top-actions"><span class="local-tag">P0–P6 · lokal geprüft</span><a href="STABILIZATION_PLAN.md" download>Plan speichern ↓</a><button id="theme-toggle" type="button" aria-label="Lesemodus wechseln">Hell</button></div></header>'
result+='<div class="frame"><header class="hero" id="top"><div class="eyebrow">Umgesetzte Entwicklungsrunde · 11. Oktober 2026</div><h1>Eine verlässliche Basis<br>für Medienwerk.</h1><p class="lede">Vorhandene Abläufe schrittweise verbinden: konsistente Einstellungen, dauerhafte Projekte und nachvollziehbare Aufträge. Weitere Anpassungen und neue Funktionen folgen danach.</p><div class="hero-meta"><span>Lokaler Betrieb für eine Person</span><span>Bestehende Technik erweitern</span><span>Kleine Änderungspakete für Original-Updates</span></div><div class="hero-actions"><a href="STABILIZATION_RESULT.md">Abschlussbericht: 96 Tests und Browserabnahme</a><a href="#section-3">Die sieben Etappen</a><a href="#section-11">Alle Analysebefunde zuordnen</a><a href="STABILIZATION_PLAN.md" download>Ausführlichen Plan speichern</a></div><div class="metrics"><div class="metric"><b>7</b><span>Etappen mit Abschlusskriterien</span></div><div class="metric"><b>3</b><span>gemeinsame Grundlagen</span></div><div class="metric"><b>15</b><span>zugeordnete Analysebefunde</span></div><div class="metric"><b>1</b><span>erster Hauptablauf: Quick Creator</span></div></div></header>'
result+='<aside class="plan-note"><strong>Lokale Stabilisierung abgeschlossen.</strong> Drei Luna/high-Worker haben die Umsetzung übernommen; der Hauptagent hat Änderungen, 96 Backend-Tests in zwei Umgebungen, den Next-Build, echte FFmpeg-Konvertierungen und Neustartfälle geprüft. Reale KI-Anbieter und Veröffentlichungen bleiben separat zu prüfen. <a href="STABILIZATION_RESULT.md">Nachweise und Grenzen</a> · <a href="MODULE_DEVELOPMENT.md">Verträge für neue Module</a></aside>'
result+='<div class="takeaways"><article class="takeaway"><small>Zuerst</small><h3>Stand sichern, Aufrufe reparieren</h3><p>Vor Migrationen sichern wir Daten und Programmstand. Dann werden Schlüssel, Optionen und konkrete fehlerhafte Methodenaufrufe vereinheitlicht.</p></article><article class="takeaway"><small>Danach</small><h3>Projekte und Jobs verbinden</h3><p>SQLite speichert den gemeinsamen Bestand. Die vorhandenen Pipelines registrieren ihre Ergebnisse, und die Oberfläche zeigt echte Zustände.</p></article><article class="takeaway"><small>Nächste Runde</small><h3>Deine Anpassungen und Funktionen</h3><p>Design, vollständiger Editor, Brand-Oberfläche, Agentenstudio und zusätzliche Publisher bekommen anschließend einen eigenen Plan.</p></article></div>'
result+='<div class="layout"><aside class="contents"><details open><summary>Plan · '+str(len(sections))+' Kapitel</summary><nav aria-label="Inhaltsverzeichnis">'+''.join(nav)+'</nav></details></aside><main>'+''.join(sections)+'<footer class="footer"><p>Gestaltung aus Medienwerk: Outfit-Schrift sowie Farben und Kartenstil aus <code>web/src/app/globals.css</code>. Der helle Modus ist eine Leseoption dieses Plans. Anwendungscode und Laufzeitdaten werden durch die Planerstellung nicht geändert.</p><a href="STABILIZATION_PLAN.md" download>Plan speichern</a><a href="PLATFORM_ANALYSIS.md" download>Analyse speichern</a><a href="#top">Zum Anfang ↑</a></footer></main></div></div><script>'+script+'</script></body></html>'
(OUT/'index.html').write_text(result)
print(f'Plan created: {len(sections)} chapters, {len(result):,} characters')
