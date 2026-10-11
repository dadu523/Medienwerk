"use client";

import { useState, useEffect } from "react";
import { Play, Square, Film, Settings, Zap, Ghost, Rocket, Landmark, ShoppingBag } from "lucide-react";
import { TabSelect } from "@/components/TabSelect";
import { ToggleSwitch } from "@/components/ToggleSwitch";
import { useConfig } from "@/context/ConfigContext";
import { apiRequest, errorMessage } from "@/lib/api";
import { JobStatus } from "@/components/JobStatus";
import { jobMediaUrl, useJob, useResumableJobId, useStartGuard } from "@/lib/jobs";

export default function CreatorStudio() {
  const [topic, setTopic] = useState("");
  const [quickPreset, setQuickPreset] = useState("Custom");
  
  const [contentStyle, setContentStyle] = useState("Documentary");
  const [style, setStyle] = useState("Cinematic Documentary");
  const [audioEngine, setAudioEngine] = useState("Gemini API");
  const [videoEngine, setVideoEngine] = useState("WaveSpeed AI");
  const [voice, setVoice] = useState("Kore");
  const [elevenVoice, setElevenVoice] = useState("Brian");
  const [aspectRatio, setAspectRatio] = useState("16:9");
  const [bgMode, setBgMode] = useState("AI Video");
  const [scriptLength, setScriptLength] = useState("Medium (~5 minutes)");
  
  const [imageCount, setImageCount] = useState(8);
  const [videoCount, setVideoCount] = useState(1);
  
  const [omnichannel, setOmnichannel] = useState(false);
  const [bgMusic, setBgMusic] = useState(true);
  const [autoCaptions, setAutoCaptions] = useState(true);
  const [factCheck, setFactCheck] = useState(false);
  const [genThumbnail, setGenThumbnail] = useState(false);
  const [genSeo, setGenSeo] = useState(false);
  const [genTimestamps, setGenTimestamps] = useState(false);
  const [genSnippets, setGenSnippets] = useState(false);

  const [jobId, setJobId] = useResumableJobId("quick_creator");
  const [startError, setStartError] = useState<string | null>(null);
  const { starting, run } = useStartGuard();
  const jobState = useJob(jobId);
  const job = jobState.job;
  const status = starting ? "starting" : job?.status || (startError ? "error" : "idle");
  const busy = starting || status === "queued" || status === "running" || status === "cancel_requested";
  const finalVideo = jobMediaUrl(job);

  const { config, status: contextStatus } = useConfig();
  const [hasInitialized, setHasInitialized] = useState(false);

  useEffect(() => {
    if (contextStatus === "idle" && Object.keys(config).length > 0 && !hasInitialized) {
      setAudioEngine(config.AUDIO_ENGINE || "Gemini API");
      setVideoEngine(config.VIDEO_ENGINE || "WaveSpeed AI");
      setVoice(config.VOICE_NAME || "Kore");
      setAspectRatio(config.VIDEO_ASPECT_RATIO || "16:9");
      setBgMode(config.BG_MODE || "AI Video");
      setScriptLength(config.SCRIPT_LENGTH || "Medium (~5 minutes)");
      setImageCount(config.IMAGE_COUNT || 8);
      setVideoCount(config.VIDEO_CLIP_COUNT || 1);
      setBgMusic(config.ADD_MUSIC ?? true);
      setAutoCaptions(config.CAPTION_ENABLED ?? true);
      setFactCheck(config.FACT_CHECK_ENABLED ?? false);
      setGenThumbnail(config.GENERATE_THUMBNAIL ?? false);
      setGenSeo(config.GENERATE_METADATA ?? false);
      setGenTimestamps(config.GENERATE_TIMESTAMPS ?? false);
      setGenSnippets(config.GENERATE_SNIPPETS ?? false);
      setContentStyle(config.CONTENT_STYLE || "Documentary");
      setHasInitialized(true);
    }
  }, [config, contextStatus, hasInitialized]);

  const handlePreset = (preset: string) => {
    setQuickPreset(preset);
    
    // Reset to defaults first for consistent behavior
    setContentStyle("Podcast");
    setStyle("Cinematic Documentary");
    setVoice("Kore");
    setAspectRatio("16:9");
    setOmnichannel(false);
    setBgMusic(true);
    setAutoCaptions(true);
    setGenSeo(false);

    if (preset === "Tech News Short") {
      setContentStyle("Viral Video");
      setStyle("TikTok Viral");
      setAudioEngine("Gemini API");
      setVoice("Kore");
      setAspectRatio("9:16");
      setOmnichannel(false);
      setGenSeo(true);
    } else if (preset === "Scary Story") {
      setContentStyle("Story");
      setStyle("Cinematic Documentary");
      setVoice("Charon");
      setAspectRatio("9:16");
      setBgMusic(true);
    } else if (preset === "Motivation / Hustle") {
      setContentStyle("Viral Video");
      setStyle("Cyberpunk / Neon");
      setVoice("Fenrir");
      setAspectRatio("9:16");
      setBgMusic(true);
      setAutoCaptions(true);
      setOmnichannel(false);
    } else if (preset === "Historical Deep Dive") {
      setContentStyle("Documentary");
      setStyle("Cinematic Documentary");
      setVoice("Kore");
      setAspectRatio("16:9");
      setGenSeo(true);
    } else if (preset === "Product Promo") {
      setContentStyle("Product Ad");
      setStyle("TikTok Viral");
      setVoice("Kore");
      setAspectRatio("1:1");
      setOmnichannel(false);
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setStartError(null);
    await run(async (idempotencyKey) => {
    try {
      const payload = {
        topic, start_point: "Deep Research", content_style: contentStyle,
        style, voice: audioEngine === "Gemini API" ? voice : elevenVoice, 
        audio_engine: audioEngine, video_engine: videoEngine, aspect_ratio: aspectRatio, bg_mode: bgMode,
        image_count: imageCount, video_count: videoCount,
        omnichannel, bg_music: bgMusic, auto_captions: autoCaptions,
        fact_check: factCheck, generate_thumbnail: genThumbnail,
        generate_seo: genSeo, generate_timestamps: genTimestamps,
        generate_snippets: genSnippets, script_length: scriptLength, idempotency_key: idempotencyKey
      };
      const data = await apiRequest<{ job_id: string }>("/api/generate/quick", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
      });
      if (!data.job_id) throw new Error("The server did not return a job ID.");
      setJobId(data.job_id);
      return data;
    } catch (err) {
      setStartError(errorMessage(err, "Could not start video generation."));
      return Promise.reject(err);
    }
    });
  };

  const handleCancel = async () => {
    if (jobId) {
      try { await apiRequest(`/api/generate/cancel/${encodeURIComponent(jobId)}`, { method: "POST" }); }
      catch (error) { setStartError(errorMessage(error, "Could not cancel this job.")); }
    }
  };

  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-in fade-in duration-500">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white tracking-tight">Quick Creator</h1>
        <p className="text-zinc-400 mt-1">Configure and launch high-retention video generation.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        <div className="lg:col-span-5 space-y-6">
          <form onSubmit={handleGenerate} className="space-y-6">
            
            <div className="glass-card p-6 space-y-6">
              <h3 className="text-xs font-bold text-white tracking-widest uppercase border-b border-white/10 pb-3 mb-4">Core Setup</h3>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Quick Presets</label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {[
                      { id: "Custom", icon: Settings },
                      { id: "Tech News Short", icon: Zap },
                      { id: "Scary Story", icon: Ghost },
                      { id: "Motivation / Hustle", icon: Rocket },
                      { id: "Historical Deep Dive", icon: Landmark },
                      { id: "Product Promo", icon: ShoppingBag },
                    ].map(preset => (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => handlePreset(preset.id)}
                        className={`flex flex-col items-center justify-center gap-2 p-3 rounded-xl border transition-all ${
                          quickPreset === preset.id 
                            ? "bg-[#66fcf1]/10 border-[#66fcf1] text-[#66fcf1]" 
                            : "bg-black/50 border-white/5 text-zinc-400 hover:bg-white/5 hover:text-white"
                        }`}
                      >
                        <preset.icon className="h-5 w-5" />
                        <span className="text-[10px] font-bold uppercase tracking-wider text-center">{preset.id}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Start From Step</label>
                  <div className="relative">
                    <select value="Deep Research" disabled className="modern-select">
                      <option value="Deep Research" className="bg-black">Deep Research (only supported start point)</option>
                    </select>
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Video Topic</label>
                <input type="text" placeholder="e.g. History of Rome" value={topic} onChange={(e) => setTopic(e.target.value)} required disabled={busy} className="modern-input" />
              </div>
            </div>

            <div className="glass-card p-6 space-y-6">
              <h3 className="text-xs font-bold text-white tracking-widest uppercase border-b border-white/10 pb-3 mb-4">Style & Persona</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Content Style</label>
                  <select value={contentStyle} onChange={e => setContentStyle(e.target.value)} className="modern-select">
                    {["Podcast", "Documentary", "Story", "Viral Video", "Product Ad"].map(s => <option key={s} value={s} className="bg-black">{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Visual Style</label>
                  <select value={style} onChange={e => setStyle(e.target.value)} className="modern-select">
                    {["Cinematic Documentary", "TikTok Viral", "Sci-Fi / Futuristic", "Cyberpunk / Neon"].map(s => <option key={s} value={s} className="bg-black">{s}</option>)}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Audio Engine</label>
                  <TabSelect options={["Gemini API", "WaveSpeed AI"]} value={audioEngine} onChange={setAudioEngine} />
                </div>
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Voice</label>
                  {audioEngine === "Gemini API" ? (
                    <TabSelect options={["Kore", "Fenrir", "Charon", "Aoede", "Puck"]} value={voice} onChange={setVoice} />
                  ) : (
                    <input type="text" value={elevenVoice} onChange={e => setElevenVoice(e.target.value)} placeholder="e.g. Brian, Rachel, or ID" className="modern-input" />
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Aspect Ratio</label>
                  <TabSelect options={["16:9", "9:16", "1:1"]} value={aspectRatio} onChange={setAspectRatio} />
                </div>
                {bgMode === "AI Video" && (
                  <div>
                    <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Video Engine</label>
                    <select value={videoEngine} onChange={e => setVideoEngine(e.target.value)} className="modern-select">
                      {["WaveSpeed AI", "Vertex AI (Veo)"].map(s => <option key={s} value={s} className="bg-black">{s}</option>)}
                    </select>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Background Mode</label>
                  <TabSelect options={["AI Video", "Stock Video (Pixabay)"]} value={bgMode} onChange={setBgMode} />
                </div>
                <div>
                  <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Video Length</label>
                  <select value={scriptLength} onChange={e => setScriptLength(e.target.value)} className="modern-select">
                    {["Micro (< 1 minute)", "Short (~2 minutes)", "Medium (~5 minutes)", "Long (~10 minutes)"].map(s => <option key={s} value={s} className="bg-black">{s}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="glass-card p-6">
              <h3 className="text-xs font-bold text-white tracking-widest uppercase border-b border-white/10 pb-3 mb-6">Advanced Options</h3>
              <div className="grid grid-cols-2 gap-y-6 gap-x-4">
                <div className="opacity-50"><ToggleSwitch checked={false} onChange={() => setOmnichannel(false)} label="Omnichannel (unavailable)" /></div>
                <ToggleSwitch checked={bgMusic} onChange={setBgMusic} label="Background Music" />
                <ToggleSwitch checked={autoCaptions} onChange={setAutoCaptions} label="Auto Captions" />
                <ToggleSwitch checked={genSeo} onChange={setGenSeo} label="SEO Metadata" />
              </div>
            </div>

            <div className="pt-2">
              {busy ? (
                <button type="button" onClick={handleCancel} className="w-full py-3.5 bg-rose-500/10 border border-rose-500/30 text-rose-400 font-bold rounded-xl hover:bg-rose-500/20 transition-all flex items-center justify-center gap-2">
                  <Square className="h-4 w-4 fill-current" /> Abort Generation
                </button>
              ) : (
                <button type="submit" disabled={busy || !topic.trim()} className="btn-primary disabled:opacity-50">
                  <Play className="h-4 w-4 fill-current" /> Generate Video
                </button>
              )}
            </div>
          </form>
        </div>

        <div className="lg:col-span-7 space-y-6">
          <div className="glass-card p-6 min-h-[500px] flex flex-col justify-between">
            <h2 className="text-xs font-bold text-white uppercase tracking-widest border-b border-white/10 pb-3 flex items-center justify-between">
              Live Monitor
              <span className="text-zinc-500">
                Job: {jobId ? `${jobId.slice(0, 8)}...` : "Idle"}
              </span>
            </h2>

            {!jobId && !startError && !starting && (
              <div className="my-auto text-center space-y-4 py-12">
                <div className="w-full max-w-lg mx-auto aspect-video bg-black border border-white/10 rounded-xl flex items-center justify-center relative overflow-hidden group">
                  <div className="p-5 bg-white/5 rounded-full text-zinc-600 group-hover:text-white transition-colors border border-white/5">
                    <Film className="h-10 w-10" />
                  </div>
                </div>
                <p className="text-sm text-zinc-500 pt-4">Configure parameters and click <span className="text-white font-bold">Generate Video</span></p>
              </div>
            )}

            {jobId && <div className="space-y-5"><JobStatus job={job} logs={jobState.logs} error={startError || jobState.error} connection={jobState.connection} onClear={() => setJobId("")} />
              {finalVideo && <div className="space-y-3"><video controls className="w-full rounded-xl" src={finalVideo} /><a className="btn-primary inline-flex" href={finalVideo} download>Download video</a></div>}
            </div>}
            {startError && !jobId && <p role="alert" className="text-sm text-rose-300">{startError}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
