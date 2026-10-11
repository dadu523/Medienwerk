"use client";

import { Video, Sparkles, Plus, Scissors, Film, ArrowRight, Activity, CalendarDays, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiRequest, errorMessage } from "@/lib/api";

interface Summary { projects: number; media: number; jobs_by_status: Record<string, number>; }
interface RecentProject { id: string; title?: string; type?: string; status?: string; created_at: string; videos?: Array<{ id?: string; title?: string; url?: string; path?: string }>; }
export default function Dashboard() {
  const [greeting, setGreeting] = useState("Welcome back");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const hour = new Date().getHours(); setGreeting(hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening");
    const controller = new AbortController();
    Promise.all([apiRequest<Summary>("/api/projects/summary", { signal: controller.signal }), apiRequest<RecentProject[]>("/api/projects/history", { signal: controller.signal })])
      .then(([stats, history]) => { setSummary(stats); setRecent(history.slice(0, 5)); })
      .catch((e) => { if (!controller.signal.aborted) setError(errorMessage(e, "Could not load project activity.")); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  const jobs = summary?.jobs_by_status || {};
  const active = (jobs.queued || 0) + (jobs.running || 0) + (jobs.awaiting_input || 0) + (jobs.cancel_requested || 0);
  const completed = jobs.completed || 0;
  const stats = [{ label: "Projects", value: summary?.projects ?? "—", icon: Video }, { label: "Registered media", value: summary?.media ?? "—", icon: Film }, { label: "Completed jobs", value: completed, icon: Sparkles }, { label: "Active jobs", value: active, icon: Activity }];
  return <div className="max-w-7xl mx-auto space-y-10 animate-in fade-in duration-700 pb-12">
    <div className="relative overflow-hidden rounded-3xl bg-black/40 border border-white/5 p-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 backdrop-blur-md"><div className="relative z-10"><div className="flex items-center gap-2 mb-2"><Sparkles className="h-4 w-4 text-[var(--accent)]" /><span className="text-[var(--accent)] text-xs font-bold tracking-widest uppercase">Medienwerk</span></div><h1 className="text-4xl md:text-5xl font-extrabold text-white tracking-tight mb-2">{greeting}, Creator.</h1><p className="text-zinc-400 text-sm md:text-base max-w-lg">{summary ? `${summary.projects} projects and ${summary.media} registered media files in your workspace.` : "Your local production workspace."}</p></div><Link href="/studio" className="btn-primary !w-auto px-8 py-4 text-base"><Plus className="h-5 w-5" />Create Video</Link></div>
    <div><h2 className="text-sm font-bold text-white uppercase tracking-widest mb-4 flex items-center gap-2"><Activity className="h-4 w-4 text-[var(--accent)]" />Launchpad</h2><div className="grid grid-cols-1 md:grid-cols-3 gap-5">{[{ title: "Quick Creator", desc: "Script to video", icon: Video, href: "/studio" }, { title: "Magic Clipper", desc: "Create shorts from footage", icon: Scissors, href: "/clipper" }, { title: "Director Mode", desc: "Process and edit a source video", icon: Film, href: "/director" }].map((action) => <Link key={action.href} href={action.href} className="glass-card glass-card-hover p-6 flex flex-col group"><div className="flex justify-between items-start mb-4"><div className="p-3 rounded-xl bg-white/5 border border-white/5 text-[var(--accent)]"><action.icon className="h-6 w-6" /></div><ArrowRight className="h-4 w-4 text-white opacity-0 group-hover:opacity-100" /></div><h3 className="text-lg font-bold text-white mb-1">{action.title}</h3><p className="text-xs text-zinc-500">{action.desc}</p></Link>)}</div></div>
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">{stats.map((stat) => <div key={stat.label} className="glass-card p-5"><div className="flex justify-between items-start mb-4"><p className="text-xs font-bold text-zinc-500 uppercase tracking-wider">{stat.label}</p><stat.icon className="h-4 w-4 text-zinc-600" /></div><p className="text-3xl font-extrabold text-white">{loading ? "…" : stat.value}</p></div>)}</div>
    <div className="glass-card p-6"><div className="flex items-center justify-between mb-6 pb-4 border-b border-white/5"><h2 className="text-sm font-bold text-white uppercase tracking-widest flex items-center gap-2"><CalendarDays className="h-4 w-4 text-zinc-400" />Recent projects</h2><Link href="/history" className="text-xs font-bold text-[var(--accent)]">View history</Link></div>
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}{loading ? <div className="flex items-center gap-2 text-sm text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" />Loading workspace data</div> : !recent.length ? <p className="text-sm text-zinc-500">No projects yet.</p> : <div className="space-y-3">{recent.map((item) => <div key={item.id} className="flex items-center justify-between gap-3 p-3 bg-black/20 rounded-xl border border-white/5"><div><h3 className="text-sm font-bold text-white">{item.title || item.type || "Project"}</h3><p className="text-[11px] text-zinc-500">{new Date(item.created_at).toLocaleString()} · {item.videos?.length || 0} videos</p></div><span className="text-[10px] uppercase text-zinc-400">{item.status || "saved"}</span></div>)}</div>}
    </div>
  </div>;
}
