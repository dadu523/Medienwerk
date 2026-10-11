"""Build the analysis artifact; runs separately from application dependencies."""
from pathlib import Path
import ast
import html
import json
import re
import shutil
import markdown

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DOC = ROOT / "docs/PLATFORM_ANALYSIS.md"
text = DOC.read_text()

def file_link(match):
    path, line = match.group(1), int(match.group(2))
    source = ROOT / path
    if not source.is_file() or line > len(source.read_text().splitlines()):
        raise ValueError(f"Invalid reference: {path}:{line}")
    return f"[{path}:{line}]({source}:{line})"

text = re.sub(r"\[\[([^\]]+):(\d+)\]\]", file_link, text)

# Capture the actual decorators rather than maintaining a separate API inventory.
if "## 16." not in text:
    main = ast.parse((ROOT / "server/main.py").read_text())
    prefixes = {}
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
            name = node.args[0].value.id
            prefixes[name] = next(k.value.value for k in node.keywords if k.arg == "prefix")
    rows = []
    for name, prefix in prefixes.items():
        source = ROOT / f"server/routers/{name}.py"
        for node in ast.walk(ast.parse(source.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr in {"get", "post", "delete", "put", "patch", "websocket"}):
                    route = prefix + decorator.args[0].value
                    rows.append(f"| {decorator.func.attr.upper()} | `{route}` | [{name}.py:{node.lineno}]({source}:{node.lineno}) |")
    text += "\n## 16. Anhang: Schnittstellen im aktuellen Code\n\n"
    text += "Diese Liste wurde aus den Router-Dekoratoren im untersuchten Arbeitsstand abgeleitet. Sie zeigt vorhandene Schnittstellen, keine Bestätigung erfolgreicher Verarbeitung. Die interaktive FastAPI-Dokumentation liegt lokal unter [localhost:8008/docs](http://localhost:8008/docs). Zusätzlich definiert `server/main.py` die Endpunkte `GET /health`, `GET /api/config` und `POST /api/config`.\n\n"
    text += "| Methode | Adresse | Implementierung |\n| --- | --- | --- |\n" + "\n".join(rows) + "\n"

DOC.write_text(text)
shutil.copyfile(DOC, OUT / "PLATFORM_ANALYSIS.md")
fonts = list((ROOT / "web/.next/static/media").glob("*-s.p.*.woff2"))
if fonts:
    shutil.copyfile(fonts[0], OUT / "outfit.woff2")

def svg_start(id, height, title):
    return f'<svg class="diagram" viewBox="0 0 380 {height}" role="img" aria-labelledby="{id}-title"><title id="{id}-title">{title}</title><defs><marker id="{id}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="var(--accent)"/></marker></defs>'

def box(id, x, y, width, title, sub, tone="normal", height=76):
    return f'<g id="{id}"><title>{html.escape(title + ": " + sub)}</title><rect class="node {tone}" x="{x}" y="{y}" width="{width}" height="{height}" rx="14"/><text x="{x+width/2}" y="{y+30}" text-anchor="middle" class="node-title">{html.escape(title)}</text><text x="{x+width/2}" y="{y+53}" text-anchor="middle" class="node-sub">{html.escape(sub)}</text></g>'

def arrow(id, x1, y1, x2, y2, svgid, label=None):
    s = f'<g id="{id}"><title>{html.escape(label or "Nächster Verarbeitungsschritt")}</title><path class="edge" d="M{x1} {y1} L{x2} {y2}" marker-end="url(#{svgid}-arrow)"/>'
    if label:
        s += f'<text class="edge-label" x="{x1+13}" y="{(y1+y2)/2+5}">{html.escape(label)}</text>'
    return s + '</g>'

architecture = svg_start("arch", 590, "Zwei lokale Server: Browser, Next.js, FastAPI und Verarbeitung")
architecture += box("arch-browser", 40, 8, 300, "Browser", "Formulare · Vorschau · Protokoll")
architecture += arrow("arch-http",190,84,190,120,"arch","HTTP / WebSocket")
architecture += box("arch-next",40,125,300,"Next.js · Port 3000","Oberfläche und API-Weiterleitung")
architecture += arrow("arch-proxy",190,201,190,237,"arch","/api/…")
architecture += box("arch-fastapi",40,242,300,"FastAPI · Port 8008","11 Gruppen von API-Endpunkten")
architecture += arrow("arch-submit",190,318,190,354,"arch","Job-ID + Hintergrundauftrag")
architecture += box("arch-worker",40,359,300,"Python-Verarbeitung","2 Worker · KI-Anbieter · FFmpeg", "accent")
architecture += arrow("arch-output",190,435,190,471,"arch","Ergebnis als Dateipfad")
architecture += box("arch-file",40,476,300,"Lokale Dateien","Video · Ton · Text · Einstellungen")
architecture += '</svg>'

quick = svg_start("quick", 510, "Die vier Phasen des Quick Creators")
for i, (title, sub) in enumerate([
    ("1 · Inhalt entwickeln", "Recherche → Review → Skript"),
    ("2 · Medien erzeugen", "Stimmen · Bilder · Videoclips"),
    ("3 · Video montieren", "FFmpeg · Untertitel · Branding"),
    ("4 · Ausgabe ergänzen", "SEO · Kapitel · 60-Sekunden-Clips")
]):
    y = 12+i*120
    quick += box(f"quick-phase-{i+1}",30,y,320,title,sub,"accent" if i==2 else "normal")
    if i < 3:
        quick += arrow(f"quick-edge-{i+1}",190,y+76,190,y+116,"quick")
quick += '</svg>'

clipper = svg_start("clip", 625, "Clipper: Analyse, Auswahl und Rendering sind getrennte Phasen")
for i, (title, sub) in enumerate([
    ("Video laden", "YouTube-URL oder lokale Datei"),
    ("Whisper + Textmodell", "Transkript → Vorschläge"),
    ("Deine Auswahl", "Clips prüfen und auswählen"),
    ("Shorts rendern", "Gesichtsausschnitt · Untertitel"),
    ("Finale Clips", "720 × 1280 · Historie erkennt sie")
]):
    y = 8+i*120
    clipper += box(f"clip-phase-{i+1}",30,y,320,title,sub,"accent" if i==2 else "normal")
    if i<4:
        clipper += arrow(f"clip-edge-{i+1}",190,y+76,190,y+116,"clip")
clipper += '</svg>'

storage = svg_start("storage", 470, "Die Historie erkennt nicht alle fertigen Produktionen")
storage += box("storage-producers",30,12,320,"Verschiedene Produktionswege","Jeder verwendet eigene Ordner")
storage += arrow("storage-output",190,88,190,122,"storage")
storage += box("storage-folder",30,127,320,"Endvideos als Dateien","Kein gemeinsames Projektregister")
storage += arrow("storage-scan",190,203,190,242,"storage","Ordner + feste Dateinamen")
storage += box("storage-history",30,247,320,"Historie findet einen Teil","Clipper + Explainer + Workspace-Podcasts","accent")
storage += box("storage-missing",30,355,320,"Andere Ergebnisse fehlen","Quick · Director · VideoFX · Agenten","warning")
storage += '</svg>'

def illustration(id, label, svg, title, description, facts):
    return f'<div class="illustration" id="{id}"><figure>{svg}<figcaption>{label}</figcaption></figure><div class="figure-text"><div class="eyebrow">So funktioniert es</div><h3>{title}</h3><p>{description}</p><ul>' + ''.join(f'<li>{x}</li>' for x in facts) + '</ul></div></div>'

inserts = {
    2: illustration("aufbau", "Aufbau aus dem lokalen Arbeitsstand", architecture, "Eine Oberfläche, zwei Server", "Du bedienst die Anwendung über Port 3000. Next.js reicht API-Aufrufe an Python weiter; dort beginnt die eigentliche Medienproduktion.", ["Der Browser zeigt Eingaben und Ergebnisse.","FastAPI validiert Aufträge und liefert eine Job-ID.","Worker erzeugen Medien; WebSockets bringen Status zurück.","SQLite speichert bisher Social-Tokens, keine Projekte."]),
    5: illustration("quick-ablauf", "14 Schritte, hier in vier Phasen zusammengefasst", quick, "Quick Creator erzeugt neue Inhalte", "Das Thema wird zuerst in ein Skript übersetzt. Daraus entstehen die Medien für das fertige Video. Zahlreiche Schritte sind optional oder verwenden bereits vorhandene Dateien.", ["<strong>Code-Befund:</strong> Analyse des Tons ist ein leerer Schritt.","<strong>Code-Befund:</strong> Dateiexistenz entscheidet über Wiederverwendung.","<strong>Code-Befund:</strong> Der Ausgabeordner liegt außerhalb der normalen Historie."]),
    6: illustration("clipper-ablauf", "Zwei Aufträge mit einer gemeinsamen Job-ID", clipper, "Im Clipper entscheidet deine Auswahl", "Die erste Phase schlägt Ausschnitte vor. Die zweite Phase macht daraus fertig gerenderte Shorts. Die Auswahl liegt zwischen beiden Verarbeitungsschritten.", ["Lokale Transkription, KI-Vorschläge und FFmpeg-Montage sind im Code vorhanden.","Die Gesichtsverfolgung wählt das größte Gesicht, ohne Sprecher anhand des Tons zu erkennen.","Die Timeline besitzt noch keine funktionierenden Schnittgriffe."]),
    9: illustration("speicher", "Warum Ergebnis und Historie auseinanderlaufen", storage, "Ein Video ist noch kein registriertes Projekt", "Die Anwendung schreibt Ergebnisse in mehrere Verzeichnisstrukturen. Historie und Publish suchen anschließend nach ausgewählten Namen. Es fehlt eine gemeinsame Quelle für den Produktionsbestand.", ["Ein fertig gerendertes Video kann auf der Produktionsseite vorhanden sein und in History fehlen.","Dashboard, History und Publish beziehen ihre Informationen aus unterschiedlichen Quellen.","<strong>Einschätzung:</strong> Ein lokales Projektregister könnte diese Verbindung herstellen."]),
}

def screenshots():
    return '<div class="screenshots"><figure><a href="dashboard.png" target="_blank"><img src="dashboard.png" alt="Echte lokale Dashboard-Seite mit Beispielkennzahlen" loading="lazy"></a><figcaption><strong>Dashboard</strong> · Die dargestellten Kennzahlen und Projekte sind fest im Code eingetragen.</figcaption></figure><figure><a href="brand.png" target="_blank"><img src="brand.png" alt="Echte Brand-Assets-Seite mit Coming-Soon-Hinweis" loading="lazy"></a><figcaption><strong>Brand Assets</strong> · Backend vorhanden, Bedienoberfläche noch ein Platzhalter.</figcaption></figure></div>'

inserts[3] = screenshots()

snippets = []
def evidence(section, path, start, end, reason):
    content = '\n'.join((ROOT/path).read_text().splitlines()[start-1:end])+'\n'
    idx = len(snippets)
    snippets.append({"name":path,"contents":content})
    return f'<details class="evidence"><summary>Quellcode ansehen · {html.escape(reason)}</summary><p class="source-note">{html.escape(path)} · Originalzeilen {start}–{end}. Der Ausschnitt beginnt im Codefenster bei Zeile 1.</p><div id="snippet-{idx}" class="code-surface" data-snippet="{idx}"></div></details>'

evidences = {
  5: evidence(5,"pipeline.py",251,263,"Quick-Creator-Ausgabeordner"),
  7: evidence(7,"server/core/scheduler.py",82,90,"Kampagne greift auf google_client zu"),
  8: evidence(8,"web/src/app/settings/page.tsx",42,46,"Gespeicherter WaveSpeed-Schlüssel") + evidence(8,"api_clients.py",203,209,"Gelesener WaveSpeed-Schlüssel") + evidence(8,"server/routers/tools.py",92,103,"Aufruf der fehlenden Sprachmethode"),
  9: evidence(9,"server/routers/generation.py",147,176,"Suchlogik der Historie"),
  12: evidence(12,"server/core/queue.py",173,177,"Abbruch und Statusänderung"),
}

parts = re.split(r'^## (\d+)\. (.+)$', text, flags=re.M)
sections, nav = [], []
for i in range(1,len(parts),3):
    num, title, body = int(parts[i]), parts[i+1], parts[i+2]
    # Local source links are rendered as evidence labels; the Markdown copy retains editor links.
    body = re.sub(r'\[([^\]]+)\]\(/home/[^)]+\)', lambda m: '`'+m.group(1)+'`', body)
    rendered = markdown.markdown(body,extensions=['tables'])
    rendered = re.sub(r'<table>', '<div class="table-wrap"><table>',rendered).replace('</table>','</table></div>')
    rendered = re.sub(r'<p>Quellen?:', '<p class="sources">Quellen:',rendered)
    sections.append(f'<section id="section-{num}" class="report-section"><div class="section-heading"><span class="section-number">{num:02}</span><h2>{html.escape(title)}</h2></div>{inserts.get(num,"")}{rendered}{evidences.get(num,"")}</section>')
    nav.append(f'<a href="#section-{num}"><span>{num:02}</span>{html.escape(title)}</a>')

css = r'''
@font-face{font-family:Outfit;src:url("outfit.woff2") format("woff2");font-weight:100 900;font-display:swap}
:root{--bg-main:#060608;--bg-glass:rgba(20,20,25,.76);--border-glass:rgba(255,255,255,.10);--accent:#66fcf1;--text:#eeeef2;--muted:#a1a1ad;--panel:#111116;--soft:rgba(255,255,255,.045);--warning:#ffcb83;--grid:rgba(255,255,255,.019);color-scheme:dark}
:root[data-theme=light]{--bg-main:#f5f7f8;--bg-glass:rgba(255,255,255,.85);--border-glass:rgba(10,30,40,.14);--accent:#006c65;--text:#182027;--muted:#54616a;--panel:#fff;--soft:rgba(20,40,60,.045);--warning:#875000;--grid:rgba(15,40,60,.035);color-scheme:light}
*{box-sizing:border-box;min-width:0}html{scroll-behavior:smooth;scroll-padding-top:92px}body{margin:0;background-color:var(--bg-main);color:var(--text);font-family:Outfit,system-ui,sans-serif;line-height:1.65;background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:40px 40px;font-size:16px}a{color:var(--accent);text-underline-offset:4px;overflow-wrap:anywhere}button{font:inherit;color:var(--text);cursor:pointer;background:var(--soft);border:1px solid var(--border-glass);padding:9px 15px;border-radius:10px}button:hover{border-color:var(--accent)}a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:4px}img{max-width:100%;display:block;border-radius:10px}p{margin:0 0 18px}h1,h2,h3{line-height:1.17;letter-spacing:-.025em}h1{font-size:clamp(39px,5vw,76px);font-weight:600;max-width:850px;margin:18px 0 24px}h2{font-size:clamp(27px,3vw,38px);font-weight:550;margin:0}h3{font-size:24px;font-weight:550;margin:30px 0 16px}ul{padding-left:22px;margin:0 0 22px}li{margin:10px 0}strong{font-weight:600}code{font-family:ui-monospace,SFMono-Regular,monospace;font-size:.82em;color:var(--accent);background:var(--soft);padding:2px 5px;border-radius:4px;overflow-wrap:anywhere;word-break:break-word}figure{margin:0}figcaption{font-size:13px;color:var(--muted);line-height:1.5;margin-top:14px}
.topbar{position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-glass);background:var(--bg-glass);backdrop-filter:blur(20px);display:flex;justify-content:space-between;align-items:center;gap:15px;padding:14px max(24px,calc((100vw - 1400px)/2))}.identity{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:600;text-decoration:none;color:var(--text)}.logo{width:30px;height:30px;border:1px solid var(--accent);border-radius:9px;display:grid;place-items:center;color:var(--accent)}.top-actions{display:flex;align-items:center;gap:14px;font-size:13px}.local-tag{border:1px solid var(--border-glass);border-radius:30px;padding:5px 10px;color:var(--muted)}.frame{max-width:1400px;margin:auto;padding:0 32px}.hero{padding:74px 0 56px}.eyebrow{text-transform:uppercase;font-size:12px;letter-spacing:.16em;color:var(--accent);font-weight:600}.lede{font-size:23px;color:var(--muted);line-height:1.5;max-width:870px}.hero-meta{display:flex;flex-wrap:wrap;gap:8px 20px;color:var(--muted);font-size:13px;margin-top:28px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:38px 0 0}.metric{border:1px solid var(--border-glass);background:var(--bg-glass);border-radius:16px;padding:22px}.metric b{display:block;color:var(--accent);font-size:38px;line-height:1.2;font-weight:500}.metric span{font-size:14px;color:var(--muted)}.takeaways{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:56px}.takeaway{padding:25px;border:1px solid var(--border-glass);border-radius:16px;background:var(--bg-glass)}.takeaway h3{font-size:21px;margin:12px 0}.takeaway p{font-size:15px;color:var(--muted);margin:0}.takeaway small{color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:.06em}.layout{display:grid;grid-template-columns:252px minmax(0,1fr);gap:48px;align-items:start}.contents{position:sticky;top:98px;max-height:calc(100vh - 115px);overflow-y:auto;padding-right:8px;font-size:13px}.contents summary{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:16px;cursor:pointer}.contents nav{display:flex;flex-direction:column;gap:3px}.contents a{padding:7px 10px;color:var(--muted);text-decoration:none;border-left:2px solid transparent;line-height:1.45}.contents a span{display:inline-block;width:25px;color:var(--accent);font-size:11px}.contents a:hover,.contents a.active{background:var(--soft);color:var(--text);border-color:var(--accent)}.report-section{padding-bottom:58px;margin-bottom:45px;border-bottom:1px solid var(--border-glass);overflow-wrap:anywhere}.section-heading{display:flex;gap:15px;align-items:baseline;margin-bottom:29px}.section-number{color:var(--accent);font-size:15px;font-weight:500}.report-section p{max-width:84ch}.sources{font-size:12px;color:var(--muted);line-height:1.9;margin-top:24px}.sources code{color:var(--muted);background:none;padding:0}.table-wrap{width:100%;margin:25px 0 30px;border:1px solid var(--border-glass);border-radius:14px;overflow:hidden}table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:14px;text-align:left;line-height:1.55}th{background:var(--soft);font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}td,th{padding:15px 16px;vertical-align:top;overflow-wrap:anywhere}td{border-top:1px solid var(--border-glass)}td:first-child{font-weight:550}tr:hover td{background:var(--soft)}table:has(th:nth-child(4)) th:first-child{width:55px}table:has(th:nth-child(4)) th:nth-child(2){width:23%}#section-16 th:first-child{width:85px}#section-16 th:nth-child(2){width:55%}
.illustration{display:grid;grid-template-columns:minmax(0, .95fr) minmax(0,1fr);gap:28px;align-items:center;background:var(--bg-glass);border:1px solid var(--border-glass);border-radius:18px;padding:28px;margin:0 0 35px}.diagram{width:100%;height:auto;max-width:380px;display:block;margin:auto;overflow:visible}.node{fill:var(--panel);stroke:var(--border-glass);stroke-width:1.5}.node.accent{stroke:var(--accent);fill:var(--soft)}.node.warning{stroke:var(--warning);stroke-dasharray:5 4}.node-title{fill:var(--text);font:500 19px Outfit,system-ui,sans-serif}.node-sub{fill:var(--muted);font:14px Outfit,system-ui,sans-serif}.edge{fill:none;stroke:var(--accent);stroke-width:1.6}.edge-label{fill:var(--muted);font:12px Outfit,system-ui,sans-serif}.figure-text h3{margin:14px 0 18px;font-size:29px}.figure-text p,.figure-text li{font-size:15px;color:var(--muted)}.screenshots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:26px 0 35px}.screenshots figure{background:var(--bg-glass);border:1px solid var(--border-glass);border-radius:15px;padding:12px}.evidence{border:1px solid var(--border-glass);background:var(--bg-glass);border-radius:13px;margin-top:16px;overflow:hidden}.evidence summary{padding:16px 20px;cursor:pointer;font-size:14px;color:var(--accent)}.source-note{padding:0 20px;font-size:12px;color:var(--muted)}.code-surface{width:100%;font-size:12px;overflow:hidden}.code-surface diffs-container{max-width:100%}.footer{margin:0 0 50px;padding:24px;border:1px solid var(--border-glass);border-radius:16px;color:var(--muted);font-size:14px}.footer a{margin-right:15px}.backtop{font-size:13px;display:inline-block;margin-top:10px}
@media(min-width:1200px){.frame{padding:0 48px}.layout{gap:60px}}
@media(max-width:1000px){.layout{grid-template-columns:minmax(0,1fr)}.contents{position:static;max-height:none;border:1px solid var(--border-glass);border-radius:15px;padding:18px;margin-bottom:15px}.contents nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.hero{padding-top:50px}.takeaways{gap:10px}.takeaway{padding:18px}}
@media(max-width:650px){.frame{padding:0 18px}.topbar{padding:12px 18px}.top-actions{gap:8px}.local-tag{display:none}.top-actions a{display:none}.hero{padding:38px 0}.lede{font-size:19px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:25px}.metric{padding:16px}.metric b{font-size:30px}.takeaways{grid-template-columns:minmax(0,1fr);margin-bottom:35px}.contents nav{grid-template-columns:minmax(0,1fr)}.illustration{grid-template-columns:minmax(0,1fr);padding:18px;gap:15px}.figure-text h3{font-size:25px}.screenshots{grid-template-columns:minmax(0,1fr)}.section-heading{gap:10px}.report-section{padding-bottom:35px;margin-bottom:35px}table{font-size:12px}td,th{padding:9px 8px}th{font-size:10px}table:has(th:nth-child(4)) th:first-child{width:36px}table:has(th:nth-child(4)) th:nth-child(2){width:20%}#section-16 th:first-child{width:60px}#section-16 th:nth-child(2){width:45%}h3{font-size:22px}.hero-meta{font-size:12px}.table-wrap{border-radius:10px}}
@media print{.contents,.topbar,button,.evidence{display:none}.layout{display:block}.frame{padding:0}.hero{padding:0 0 20px}.report-section{break-inside:avoid}body{background:white;color:black;font-size:11pt}.metric b{color:#006c65}}
'''

script = r'''
const root=document.documentElement;
document.getElementById('theme-toggle').addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='light'?'dark':'light';document.getElementById('theme-toggle').textContent=root.dataset.theme==='light'?'Dunkel':'Hell';window.dispatchEvent(new Event('report-theme'))});
const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(entry.isIntersecting){document.querySelectorAll('.contents a').forEach(a=>a.classList.toggle('active',a.hash==='#'+entry.target.id));}}},{rootMargin:'-10% 0px -75% 0px'});
document.querySelectorAll('.report-section').forEach(s=>observer.observe(s));
'''
code_script = r'''
import {File} from "https://esm.sh/@pierre/diffs@1.2.10?bundle";
const files=JSON.parse(document.getElementById('source-data').textContent);
function render(container){container.replaceChildren();new File({theme:{light:"github-light",dark:"github-dark"},themeType:document.documentElement.dataset.theme==='light'?'light':'dark',overflow:"wrap"}).render({containerWrapper:container,file:files[Number(container.dataset.snippet)]});container.dataset.rendered='yes';}
document.querySelectorAll('.evidence').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)render(d.querySelector('.code-surface'))}));
window.addEventListener('report-theme',()=>document.querySelectorAll('.evidence[open] .code-surface').forEach(render));
'''

result = '<!DOCTYPE html><html lang="de" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark light"><title>Medienwerk · Plattformanalyse</title><style>'+css+'</style></head><body>'
result += '<header class="topbar"><a class="identity" href="#top"><span class="logo" aria-hidden="true">M</span>Medienwerk <span style="color:var(--muted);font-weight:400">/ Analyse</span></a><div class="top-actions"><span class="local-tag">Lokaler Arbeitsstand</span><a href="PLATFORM_ANALYSIS.md" download>Dokumentation ↓</a><button id="theme-toggle" type="button" aria-label="Lesemodus wechseln">Hell</button></div></header>'
result += '<div class="frame"><header class="hero" id="top"><div class="eyebrow">Bestandsaufnahme · 11. Oktober 2026</div><h1>Wie Medienwerk<br>aufgebaut ist.</h1><p class="lede">Mehrere echte Produktionswege unter einer gemeinsamen Oberfläche. Projekte, Einstellungen und Auftragszustände verbinden diese Wege bisher nur teilweise.</p><div class="hero-meta"><span>Basis: <code>1733f03</code> + lokale Anpassungen</span><span>Quellcodeanalyse mit konkreten Belegen</span><span>Keine neue KI-Produktion ausgelöst</span></div><div class="metrics"><div class="metric"><b>13</b><span>Seiten in der Oberfläche</span></div><div class="metric"><b>11</b><span>API-Routergruppen</span></div><div class="metric"><b>5</b><span>sichtbare Produktionswege</span></div><div class="metric"><b>2</b><span>zentrale Arbeitsthreads</span></div></div></header>'
result += '<div class="takeaways"><article class="takeaway"><small>Aufbau</small><h3>Next.js + FastAPI</h3><p>Der Browser bedient das Studio. Python verarbeitet Medien und bindet KI-Anbieter ein. FFmpeg und Whisper übernehmen lokale Arbeit.</p></article><article class="takeaway"><small>Code-Befund</small><h3>Oberfläche und Funktion trennen</h3><p>Dashboard-Daten, Social-Verbindungen und Teile des Editors sind Beispiele oder Platzhalter. Andere Abläufe sind tatsächlich implementiert.</p></article><article class="takeaway"><small>Einschätzung</small><h3>Die Verbindung zuerst stärken</h3><p>Ein gemeinsamer Projektbestand, ein eindeutiges Konfigurationsschema und klare Jobs erleichtern die anschließenden Anpassungen.</p></article></div>'
result += '<div class="layout"><aside class="contents"><details open><summary>Inhalt · 16 Kapitel</summary><nav aria-label="Inhaltsverzeichnis">'+''.join(nav)+'</nav></details></aside><main>'+''.join(sections)+'<footer class="footer"><p>Gestaltung aus der Anwendung: Outfit-Schrift, dunkle Glasflächen und türkise Akzente aus <code>web/src/app/globals.css</code>. Der helle Modus ist eine Leseoption dieses Berichts. Screenshots zeigen den tatsächlichen lokalen Zustand.</p><a href="PLATFORM_ANALYSIS.md" download>Analyse als Markdown speichern</a><a href="clipper.png" target="_blank">Screenshot: Clipper</a><br><a class="backtop" href="#top">Zurück zum Anfang ↑</a></footer></main></div></div>'
result += '<script>'+script+'</script><script type="application/json" id="source-data">'+json.dumps(snippets,ensure_ascii=False).replace('</','<\/')+'</script><script type="module">'+code_script+'</script></body></html>'
(OUT/'index.html').write_text(result)
print(f"Report created: {len(sections)} chapters, {len(snippets)} code excerpts, {len(result):,} HTML characters")
