"use client";

import { useEffect, useState } from "react";
import { Film, FileText, Download, Trash2, Calendar, Loader2, RefreshCw, Music } from "lucide-react";
import { apiRequest, errorMessage } from "@/lib/api";

interface MediaItem { id?: string; title?: string; name?: string; path?: string; url?: string; media_type?: string; }
interface Project { id: string; title?: string; type?: string; status?: string; created_at: string; videos: MediaItem[]; audios?: MediaItem[]; scripts: Array<string | MediaItem>; }
const mediaHref = (item: MediaItem) => item.url || (item.id ? `/api/projects/media/${encodeURIComponent(item.id)}/download` : item.path ? `/api/generate/media?path=${encodeURIComponent(item.path)}` : "#");

export default function HistoryPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fetchHistory = async () => {
    setLoading(true); setError(null);
    try { setProjects(await apiRequest<Project[]>("/api/projects/history", { cache: "no-store" })); }
    catch (e) { setError(errorMessage(e, "Could not load project history.")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void fetchHistory(); }, []);
  const handleDelete = async (id: string) => {
    if (!confirm("Delete this project and its project-owned media?")) return;
    setDeletingId(id); setError(null);
    try { await apiRequest(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" }); setProjects((items) => items.filter((item) => item.id !== id)); }
    catch (e) { setError(errorMessage(e, "Could not delete this project.")); }
    finally { setDeletingId(null); }
  };
  const formatDate = (value: string) => { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); };
  const renderVideo = (item: MediaItem, index: number, type?: string) => {
    const href = mediaHref(item);
    return <div key={item.id || `${item.title}-${index}`} className="flex flex-col gap-3 group">
      <div className={`bg-black rounded-xl border border-white/10 overflow-hidden relative shadow-lg ${type === "clipper" ? "aspect-[9/16]" : "aspect-video"}`}><video src={href} controls className="w-full h-full object-cover" /></div>
      <div className="px-1"><p className="text-sm font-bold text-white line-clamp-1" title={item.title || item.name}>{item.title || item.name || "Video"}</p>
        <a href={href} download className="mt-3 py-2 w-full bg-white/5 hover:bg-white/10 text-white rounded-lg flex items-center justify-center gap-2 text-xs font-bold transition-all border border-white/10"><Download className="h-4 w-4" /> Download video</a></div>
    </div>;
  };

  return <div className="max-w-6xl mx-auto space-y-6 animate-in fade-in duration-500 pb-20">
    <div className="mb-8 flex justify-between items-end"><div><h1 className="text-3xl font-bold text-white tracking-tight">History &amp; Projects</h1><p className="text-zinc-400 mt-1">View, play, and download registered project media.</p></div>
      <button onClick={() => void fetchHistory()} disabled={loading} className="p-3 bg-white/5 hover:bg-white/10 text-white rounded-lg transition-all" title="Refresh"><RefreshCw className={`h-5 w-5 ${loading ? "animate-spin text-[#66fcf1]" : ""}`} /></button></div>
    {error && <p role="alert" className="rounded-lg bg-rose-500/10 p-3 text-sm text-rose-300">{error}</p>}
    {loading && projects.length === 0 ? <div className="glass-card p-20 flex flex-col items-center justify-center gap-4 text-zinc-400"><Loader2 className="h-10 w-10 animate-spin text-[#66fcf1]" /><p>Loading project history...</p></div>
      : projects.length === 0 ? <div className="glass-card p-20 flex flex-col items-center justify-center gap-4 text-zinc-500"><Film className="h-16 w-16 opacity-20" /><p className="text-lg">No projects found.</p></div>
        : <div className="space-y-12">{projects.map((project) => <section key={project.id} className="flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-2"><div className="flex items-center gap-3"><div className="p-2 rounded-md bg-[#66fcf1]/20 text-[#66fcf1]"><Film className="h-5 w-5" /></div>
            <div><h2 className="text-lg font-bold text-white">{project.title || project.type || "Project"}</h2><p className="text-xs text-zinc-500">{project.status || "saved"} · {formatDate(project.created_at)}</p></div></div>
            <button onClick={() => void handleDelete(project.id)} disabled={deletingId === project.id} className="p-2 text-red-400/70 hover:text-red-400 hover:bg-red-400/10 rounded-md transition-all" title="Delete project">{deletingId === project.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}</button></div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">{(project.videos || []).map((item, i) => renderVideo(item, i, project.type))}</div>
          {!!project.audios?.length && <div className="grid gap-3">{project.audios.map((audio, i) => <div key={audio.id || i} className="glass-card p-4 flex items-center gap-3"><Music className="h-5 w-5 text-[#66fcf1]" /><div className="min-w-0 flex-1"><p className="text-sm text-white truncate">{audio.title || audio.name || "Generated audio"}</p><audio controls className="mt-2 h-9 w-full" src={mediaHref(audio)} /></div><a href={mediaHref(audio)} download className="text-xs text-[#66fcf1] inline-flex gap-2"><Download className="h-4 w-4" />Download</a></div>)}</div>}
          {!!project.scripts?.length && <div className="flex flex-wrap gap-3 mt-2">{project.scripts.map((raw, i) => { const item = typeof raw === "string" ? { path: raw } : raw; const href = mediaHref(item); return <a key={item.id || i} href={href} download className="py-2 px-4 bg-white/5 hover:bg-white/10 border border-white/10 text-zinc-300 rounded-lg flex items-center gap-2 text-sm font-medium transition-all"><FileText className="h-4 w-4" />Download Script</a>; })}</div>}
        </section>)}</div>}
  </div>;
}
