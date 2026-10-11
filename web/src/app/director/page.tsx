"use client";

import { useState } from "react";
import { Film, Upload, Loader2, Play, Download, Wand2, Settings2, FileAudio } from "lucide-react";
import { apiRequest, errorMessage } from "@/lib/api";
import { useJob, useResumableJobId, useStartGuard, jobMediaUrl } from "@/lib/jobs";
import { JobStatus } from "@/components/JobStatus";

export default function DirectorModePage() {
  const [url, setUrl] = useState("");
  const [jobId, setJobId] = useResumableJobId("director");
  const [startError, setStartError] = useState<string | null>(null);
  const start = useStartGuard();
  const jobState = useJob(jobId);
  const job = jobState.job;
  const status = start.starting ? "processing" : job?.status || (startError ? "failed" : "idle");
  const busy = start.starting || status === "processing" || status === "queued" || status === "running" || status === "cancel_requested";
  const finalVideo = jobMediaUrl(job);
  
  // Settings
  const [removeSilence, setRemoveSilence] = useState(true);
  const [addPunchIns, setAddPunchIns] = useState(true);
  const [addSfx, setAddSfx] = useState(true);
  

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url) {
      alert("Please enter a video URL");
      return;
    }
    
    setStartError(null);
    await start.run(async (key) => {
    try {
      const data = await apiRequest<{ job_id: string }>("/api/director/process", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ 
          url: url,
          remove_silence: removeSilence,
          add_punch_ins: addPunchIns,
          add_sfx: addSfx, idempotency_key: key
        })
      });
      if (!data.job_id) throw new Error("The server did not return a job ID.");
      setJobId(data.job_id); return data;
    } catch (err) {
      setStartError(errorMessage(err, "Could not start Director Mode.")); throw err;
    }
    });
  };

  return (
    <div className="max-w-[1400px] mx-auto animate-in fade-in duration-500 flex flex-col h-[calc(100vh-6rem)]">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
          <Film className="h-8 w-8 text-[#66fcf1]" /> Director Mode
        </h1>
        <p className="text-zinc-400 mt-1">Autonomous AI video editor. Upload raw footage and let the AI edit it like MrBeast.</p>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-8 overflow-hidden">
        
        {/* Left Side: Input & Progress */}
        <div className="lg:col-span-5 flex flex-col space-y-6">
          <div className="glass-card p-6">
            <form onSubmit={handleGenerate} className="space-y-6">
              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider flex items-center gap-2">
                  <Upload className="h-4 w-4" /> Raw Video URL (YouTube or Direct Link)
                </label>
                <input 
                  type="text" 
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  placeholder="https://..."
                  className="modern-input"
                  disabled={status === "processing" || status === "queued" || status === "running"}
                />
              </div>

              <div className="space-y-3 pt-2">
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider flex items-center gap-2">
                  <Settings2 className="h-4 w-4" /> Editing Directives
                </label>
                
                <label className="flex items-center gap-3 p-3 bg-black/40 border border-white/5 rounded-xl cursor-pointer hover:bg-white/5 transition-all">
                  <input type="checkbox" checked={removeSilence} onChange={e => setRemoveSilence(e.target.checked)} className="w-4 h-4 accent-[#66fcf1]" disabled={busy} />
                  <div className="flex-1">
                    <p className="text-sm font-bold text-white">Silence & Umm Removal</p>
                    <p className="text-xs text-zinc-500">Automatically trims dead air for hyper-fast pacing.</p>
                  </div>
                  <FileAudio className="h-5 w-5 text-zinc-600" />
                </label>

                <label className="flex items-center gap-3 p-3 bg-black/40 border border-white/5 rounded-xl cursor-pointer hover:bg-white/5 transition-all">
                  <input type="checkbox" checked={addPunchIns} onChange={e => setAddPunchIns(e.target.checked)} className="w-4 h-4 accent-[#66fcf1]" disabled={busy} />
                  <div className="flex-1">
                    <p className="text-sm font-bold text-white">Dynamic Punch-ins</p>
                    <p className="text-xs text-zinc-500">Auto-zooms camera on high-impact sentences.</p>
                  </div>
                  <Film className="h-5 w-5 text-zinc-600" />
                </label>

                <label className="flex items-center gap-3 p-3 bg-black/40 border border-white/5 rounded-xl cursor-pointer hover:bg-white/5 transition-all">
                  <input type="checkbox" checked={addSfx} onChange={e => setAddSfx(e.target.checked)} className="w-4 h-4 accent-[#66fcf1]" disabled={busy} />
                  <div className="flex-1">
                    <p className="text-sm font-bold text-white">Keyword Sound Effects</p>
                    <p className="text-xs text-zinc-500">Injects swoosh and pop sounds to emphasize text.</p>
                  </div>
                  <Wand2 className="h-5 w-5 text-zinc-600" />
                </label>
              </div>

              <div className="pt-4">
                {busy ? (
                  <button type="button" disabled className="w-full py-4 bg-white/20 text-white font-bold rounded-xl flex items-center justify-center gap-2 cursor-not-allowed">
                    <Loader2 className="h-5 w-5 animate-spin" /> Auto-Editing Video...
                  </button>
                ) : (
                  <button type="submit" className="w-full py-4 bg-[#66fcf1] text-black font-bold rounded-xl hover:bg-[#45f3e5] transition-all shadow-[0_0_20px_rgba(102,252,241,0.3)] flex items-center justify-center gap-2">
                    <Wand2 className="h-5 w-5" /> Start Director Mode
                  </button>
                )}
              </div>
            </form>
          </div>

          {status !== "idle" && (
            <div className="glass-card p-6 flex flex-col gap-4 flex-1">
              <h2 className="text-xs font-bold text-white uppercase tracking-widest border-b border-white/10 pb-3">
                Live Timeline
              </h2>
              <JobStatus job={job} logs={jobState.logs} error={startError || jobState.error} connection={jobState.connection} onClear={() => setJobId("")} />
            </div>
          )}
        </div>

        {/* Right Side: Results */}
        <div className="lg:col-span-7 flex flex-col">
          <div className="glass-card p-6 flex-1 flex flex-col overflow-hidden">
            <h2 className="text-xs font-bold text-white uppercase tracking-widest border-b border-white/10 pb-3 mb-6 flex justify-between items-center">
              <span>Final Edited Video</span>
            </h2>
            
            <div className="flex-1 flex flex-col items-center justify-center h-full">
              {!finalVideo ? (
                <div className="text-zinc-500 flex-col gap-4 flex items-center">
                  <Film className="h-12 w-12 opacity-20" />
                  <p>Awaiting raw footage...</p>
                </div>
              ) : (
                <div className="w-full max-w-2xl mx-auto flex flex-col gap-6">
                  <div className="aspect-video bg-black rounded-xl border border-white/10 overflow-hidden relative shadow-2xl">
                    <video 
                      src={finalVideo}
                      controls 
                      className="w-full h-full object-cover"
                    />
                  </div>
                  
                  <div className="flex items-center gap-3">
                    <a href={finalVideo} download className="flex-1 py-4 bg-[#66fcf1] hover:bg-[#45f3e5] text-black rounded-xl flex items-center justify-center gap-2 text-sm font-bold transition-all shadow-[0_0_15px_rgba(102,252,241,0.2)]">
                      <Download className="h-5 w-5" /> Download Final Master
                    </a>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
