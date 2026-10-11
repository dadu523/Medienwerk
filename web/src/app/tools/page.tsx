"use client";

import { useState } from "react";
import { Type, Crop, Mic, Upload, Download, Loader2 } from "lucide-react";
import { apiRequest, errorMessage } from "@/lib/api";
import { JobStatus } from "@/components/JobStatus";
import { jobMediaUrl, useJob, useResumableJobId, useStartGuard } from "@/lib/jobs";

export default function ToolsPage() {
  // Caption State
  const [captionFile, setCaptionFile] = useState<File | null>(null);
  const [captionStyle, setCaptionStyle] = useState("Podcast");
  const [captionLang, setCaptionLang] = useState("English");
  const [captionJobId, setCaptionJobId] = useResumableJobId("tool_caption");
  const [captionError, setCaptionError] = useState<string | null>(null);
  const [captionOutput, setCaptionOutput] = useState<string | null>(null);
  const captionStart = useStartGuard();
  const captionJob = useJob(captionJobId);

  // AR State
  const [arFile, setArFile] = useState<File | null>(null);
  const [targetAr, setTargetAr] = useState("9:16");
  const [arJobId, setArJobId] = useResumableJobId("tool_ratio");
  const [arError, setArError] = useState<string | null>(null);
  const [arOutput, setArOutput] = useState<string | null>(null);
  const arStart = useStartGuard();
  const arJob = useJob(arJobId);

  // TTS State
  const [ttsText, setTtsText] = useState("");
  const [ttsVoice, setTtsVoice] = useState("Kore");
  const [ttsJobId, setTtsJobId] = useResumableJobId("tool_tts");
  const [ttsError, setTtsError] = useState<string | null>(null);
  const [ttsOutput, setTtsOutput] = useState<string | null>(null);
  const ttsStart = useStartGuard();
  const ttsJob = useJob(ttsJobId);

  const handleCaption = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!captionFile) return;
    setCaptionError(null);
    await captionStart.run(async (key) => {
    const formData = new FormData();
    formData.append("file", captionFile);
    formData.append("style", captionStyle);
    formData.append("language", captionLang);
    formData.append("idempotency_key", key);

    try {
      const data = await apiRequest<{ job_id: string }>("/api/tools/caption", {
        method: "POST",
        headers: { "Idempotency-Key": key }, body: formData
      });
      if (!data.job_id) throw new Error("The server did not return a job ID.");
      setCaptionJobId(data.job_id); return data;
    } catch (e) {
      setCaptionError(errorMessage(e, "Caption job could not start.")); throw e;
    }
    });
  };

  const handleConvert = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!arFile) return;
    setArError(null);
    await arStart.run(async (key) => {
    const formData = new FormData();
    formData.append("file", arFile);
    formData.append("target_ar", targetAr);
    formData.append("idempotency_key", key);

    try {
      const data = await apiRequest<{ job_id: string }>("/api/tools/convert", {
        method: "POST",
        headers: { "Idempotency-Key": key }, body: formData
      });
      if (!data.job_id) throw new Error("The server did not return a job ID.");
      setArJobId(data.job_id); return data;
    } catch (e) {
      setArError(errorMessage(e, "Conversion job could not start.")); throw e;
    }
    });
  };

  const handleTTS = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ttsText) return;
    setTtsError(null);
    await ttsStart.run(async (key) => {
    try {
      const data = await apiRequest<{ job_id: string }>("/api/tools/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ text: ttsText, voice: ttsVoice, idempotency_key: key })
      });
      if (!data.job_id) throw new Error("The server did not return a job ID.");
      setTtsJobId(data.job_id); return data;
    } catch (e) {
      setTtsError(errorMessage(e, "TTS job could not start.")); throw e;
    }
    });
  };

  return (
    <div className="max-w-[1400px] mx-auto animate-in fade-in duration-500">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white tracking-tight">Video Tools</h1>
        <p className="text-zinc-400 mt-1">Standalone utilities for rapid audio and video manipulation.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        
        {/* Tool 1: Auto-Captioner */}
        <div className="glass-card p-6 flex flex-col">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 rounded-lg bg-blue-500/20 text-blue-400">
              <Type className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Auto-Captioner</h2>
              <p className="text-xs text-zinc-400">Burn animated subs into any video</p>
            </div>
          </div>

          <form onSubmit={handleCaption} className="space-y-4 flex-1 flex flex-col">
            <div className="flex-1 space-y-4">
              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Source Video</label>
                <div className="relative">
                  <input type="file" accept="video/mp4" onChange={e => setCaptionFile(e.target.files?.[0] || null)} className="hidden" id="cap-file" />
                  <label htmlFor="cap-file" className="flex items-center justify-center gap-2 p-4 rounded-xl border border-dashed border-white/20 hover:border-white/50 hover:bg-white/5 transition-all cursor-pointer text-sm font-medium text-zinc-300">
                    <Upload className="h-4 w-4" /> {captionFile ? captionFile.name : 'Upload MP4...'}
                  </label>
                </div>
              </div>
              
              <div>
                <label htmlFor="caption-style" className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Style</label>
                <select id="caption-style" value={captionStyle} onChange={e => setCaptionStyle(e.target.value)} className="modern-select">
                  <option className="bg-black" value="Hormozi">Hormozi Style</option>
                  <option className="bg-black" value="Podcast">Podcast Style</option>
                </select>
              </div>
            </div>

            <div className="pt-4 border-t border-white/10 mt-auto">
              {captionStart.starting ? (
                <button disabled className="w-full py-3 bg-white/20 text-white font-bold rounded-xl flex justify-center items-center gap-2">
                  <Loader2 className="h-5 w-5 animate-spin" /> Processing...
                </button>
              ) : captionJobId ? (
                <div className="space-y-3"><JobStatus job={captionJob.job} logs={captionJob.logs} error={captionError || captionJob.error} connection={captionJob.connection} onClear={() => { const output = jobMediaUrl(captionJob.job); if (output) setCaptionOutput(output); setCaptionJobId(""); }} />
                  {captionJob.job?.status === "completed" && jobMediaUrl(captionJob.job) && <a href={jobMediaUrl(captionJob.job)!} download className="btn-primary inline-flex"><Download className="h-5 w-5" /> Download Result</a>}</div>
              ) : (
                <div className="space-y-3">{captionOutput && <a href={captionOutput} download className="btn-primary inline-flex"><Download className="h-5 w-5" /> Download last result</a>}
                  <button type="submit" className="w-full py-3 bg-white text-black font-bold rounded-xl hover:bg-zinc-200 transition-all shadow-[0_0_15px_rgba(255,255,255,0.2)]">Generate Captions</button></div>
              )}
              {captionError && !captionJobId && <p role="alert" className="mt-2 text-xs text-rose-300">{captionError}</p>}
            </div>
          </form>
        </div>

        {/* Tool 2: AR Converter */}
        <div className="glass-card p-6 flex flex-col">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 rounded-lg bg-fuchsia-500/20 text-fuchsia-400">
              <Crop className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Ratio Converter</h2>
              <p className="text-xs text-zinc-400">Resize videos for TikTok / YouTube</p>
            </div>
          </div>

          <form onSubmit={handleConvert} className="space-y-4 flex-1 flex flex-col">
            <div className="flex-1 space-y-4">
              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Source Video</label>
                <div className="relative">
                  <input type="file" accept="video/mp4" onChange={e => setArFile(e.target.files?.[0] || null)} className="hidden" id="ar-file" />
                  <label htmlFor="ar-file" className="flex items-center justify-center gap-2 p-4 rounded-xl border border-dashed border-white/20 hover:border-white/50 hover:bg-white/5 transition-all cursor-pointer text-sm font-medium text-zinc-300">
                    <Upload className="h-4 w-4" /> {arFile ? arFile.name : 'Upload MP4...'}
                  </label>
                </div>
              </div>
              
              <div>
                <label htmlFor="target-ratio" className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Target Ratio</label>
                <select id="target-ratio" value={targetAr} onChange={e => setTargetAr(e.target.value)} className="modern-select">
                  <option className="bg-black" value="9:16">9:16 (TikTok / Shorts)</option>
                  <option className="bg-black" value="16:9">16:9 (YouTube)</option>
                  <option className="bg-black" value="1:1">1:1 (Instagram)</option>
                </select>
              </div>
            </div>

            <div className="pt-4 border-t border-white/10 mt-auto">
              {arStart.starting ? (
                <button disabled className="w-full py-3 bg-white/20 text-white font-bold rounded-xl flex justify-center items-center gap-2">
                  <Loader2 className="h-5 w-5 animate-spin" /> Processing...
                </button>
              ) : arJobId ? (
                <div className="space-y-3"><JobStatus job={arJob.job} logs={arJob.logs} error={arError || arJob.error} connection={arJob.connection} onClear={() => { const output = jobMediaUrl(arJob.job); if (output) setArOutput(output); setArJobId(""); }} />
                  {arJob.job?.status === "completed" && jobMediaUrl(arJob.job) && <a href={jobMediaUrl(arJob.job)!} download className="btn-primary inline-flex"><Download className="h-5 w-5" /> Download Result</a>}</div>
              ) : (
                <div className="space-y-3">{arOutput && <a href={arOutput} download className="btn-primary inline-flex"><Download className="h-5 w-5" /> Download last result</a>}
                  <button type="submit" className="w-full py-3 bg-white text-black font-bold rounded-xl hover:bg-zinc-200 transition-all shadow-[0_0_15px_rgba(255,255,255,0.2)]">Convert Ratio</button></div>
              )}
              {arError && !arJobId && <p role="alert" className="mt-2 text-xs text-rose-300">{arError}</p>}
            </div>
          </form>
        </div>

        {/* Tool 3: TTS Generator */}
        <div className="glass-card p-6 flex flex-col">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-3 rounded-lg bg-amber-500/20 text-amber-400">
              <Mic className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">AI Voice (TTS)</h2>
              <p className="text-xs text-zinc-400">Generate studio-quality voiceovers</p>
            </div>
          </div>

          <form onSubmit={handleTTS} className="space-y-4 flex-1 flex flex-col">
            <div className="flex-1 space-y-4">
              <div>
                <label htmlFor="tts-script" className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Script</label>
                <textarea 
                  id="tts-script"
                  value={ttsText} 
                  onChange={e => setTtsText(e.target.value)} 
                  className="modern-input min-h-[120px] resize-y" 
                  placeholder="Enter text to speak..." 
                  required 
                />
              </div>
              
              <div>
                <label htmlFor="tts-voice" className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Voice Profile</label>
                <select id="tts-voice" value={ttsVoice} onChange={e => setTtsVoice(e.target.value)} className="modern-select">
                  <option className="bg-black" value="Kore">Kore (Standard Male)</option>
                  <option className="bg-black" value="Aoede">Aoede (Standard Female)</option>
                  <option className="bg-black" value="Charon">Charon (Deep/Gritty Male)</option>
                  <option className="bg-black" value="Fenrir">Fenrir (Hype Male)</option>
                </select>
              </div>
            </div>

            <div className="pt-4 border-t border-white/10 mt-auto">
              {ttsStart.starting ? (
                <button disabled className="w-full py-3 bg-white/20 text-white font-bold rounded-xl flex justify-center items-center gap-2">
                  <Loader2 className="h-5 w-5 animate-spin" /> Generating...
                </button>
              ) : ttsJobId ? (
                <div className="space-y-3">
                  <JobStatus job={ttsJob.job} logs={ttsJob.logs} error={ttsError || ttsJob.error} connection={ttsJob.connection} onClear={() => { const output = jobMediaUrl(ttsJob.job); if (output) setTtsOutput(output); setTtsJobId(""); }} />
                  {ttsJob.job?.status === "completed" && jobMediaUrl(ttsJob.job) && <><audio controls className="w-full h-10" src={jobMediaUrl(ttsJob.job)!} />
                  <a href={jobMediaUrl(ttsJob.job)!} download className="w-full py-2 bg-white/10 text-white border border-white/20 text-sm font-bold rounded-lg flex justify-center items-center gap-2 hover:bg-white/20 transition-all"><Download className="h-4 w-4" /> Download audio</a></>}
                </div>
              ) : (
                <div className="space-y-3">{ttsOutput && <><audio controls className="w-full h-10" src={ttsOutput} /><a href={ttsOutput} download className="w-full py-2 bg-white/10 text-white border border-white/20 text-sm font-bold rounded-lg flex justify-center items-center gap-2 hover:bg-white/20 transition-all"><Download className="h-4 w-4" /> Download last audio</a></>}
                  <button type="submit" className="w-full py-3 bg-white text-black font-bold rounded-xl hover:bg-zinc-200 transition-all shadow-[0_0_15px_rgba(255,255,255,0.2)]">Generate Audio</button></div>
              )}
              {ttsError && !ttsJobId && <p role="alert" className="mt-2 text-xs text-rose-300">{ttsError}</p>}
            </div>
          </form>
        </div>

      </div>
    </div>
  );
}
