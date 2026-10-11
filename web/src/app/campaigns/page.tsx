"use client";

import { useState, useEffect } from "react";
import { Plus, Play, Pause, Trash2, Bot, Clock, Sparkles } from "lucide-react";
import { apiRequest, errorMessage } from "@/lib/api";

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<any[]>([]);
  
  // New Campaign Form
  const [name, setName] = useState("");
  const [niche, setNiche] = useState("");
  const [preset, setPreset] = useState("Tech News Short");
  const [frequency, setFrequency] = useState("24"); // hours
  const [error, setError] = useState<string | null>(null);

  const fetchCampaigns = async () => {
    try {
      const data = await apiRequest<{ campaigns?: any[] }>("/api/campaigns", { cache: "no-store" });
      setCampaigns(data.campaigns || []);
    } catch (e) {
      setError(errorMessage(e, "Could not load campaigns."));
    }
  };

  useEffect(() => {
    fetchCampaigns();
    // Refresh every 30 seconds to update 'last run' times
    const int = setInterval(fetchCampaigns, 30000);
    return () => clearInterval(int);
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !niche) return;
    try {
      await apiRequest("/api/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, niche, preset, frequency_hours: parseFloat(frequency) })
      });
      setName("");
      setNiche("");
      fetchCampaigns();
    } catch (e) {
      setError(errorMessage(e, "Could not create a paused campaign."));
    }
  };

  const handleToggle = async (cid: string) => {
    setError("Campaign scheduling is paused in this build.");
  };

  const handleDelete = async (cid: string) => {
    if (!confirm("Are you sure?")) return;
    try { await apiRequest(`/api/campaigns/${encodeURIComponent(cid)}`, { method: "DELETE" }); await fetchCampaigns(); }
    catch (e) { setError(errorMessage(e, "Could not delete campaign.")); }
  };

  return (
    <div className="max-w-[1400px] mx-auto animate-in fade-in duration-500">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3">
          <Bot className="h-8 w-8 text-[#66fcf1]" /> Auto-Pilot Campaigns
        </h1>
        <p className="text-zinc-400 mt-1">Campaigns can be saved paused. Automatic scheduling is currently disabled.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Side: Create New Campaign */}
        <div className="lg:col-span-4">
          <div className="glass-card p-6">
            <h2 className="text-xs font-bold text-white uppercase tracking-widest border-b border-white/10 pb-3 mb-6 flex items-center gap-2">
              <Plus className="h-4 w-4 text-[#66fcf1]" /> Deploy New Bot
            </h2>

            <form onSubmit={handleCreate} className="space-y-5">
              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Campaign Name</label>
                <input 
                  type="text" 
                  value={name} 
                  onChange={e => setName(e.target.value)} 
                  placeholder="e.g. Daily Tech Short" 
                  className="modern-input" 
                  required 
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Niche / Broad Topic</label>
                <input 
                  type="text" 
                  value={niche} 
                  onChange={e => setNiche(e.target.value)} 
                  placeholder="e.g. AI News, Scary Stories" 
                  className="modern-input" 
                  required 
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Style Preset</label>
                <select value={preset} onChange={e => setPreset(e.target.value)} className="modern-select">
                  <option className="bg-black" value="Tech News Short">Tech News Short (9:16)</option>
                  <option className="bg-black" value="Scary Story">Scary Story (9:16)</option>
                  <option className="bg-black" value="Motivation / Hustle">Motivation (9:16)</option>
                  <option className="bg-black" value="Historical Deep Dive">Historical Deep Dive (16:9)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-zinc-500 mb-2 uppercase tracking-wider">Frequency</label>
                <select value={frequency} onChange={e => setFrequency(e.target.value)} className="modern-select">
                  <option className="bg-black" value="1">Every 1 Hour</option>
                  <option className="bg-black" value="12">Every 12 Hours</option>
                  <option className="bg-black" value="24">Every 24 Hours</option>
                  <option className="bg-black" value="168">Weekly</option>
                </select>
              </div>

              <button type="submit" className="w-full py-3 bg-white text-black font-bold rounded-xl hover:bg-zinc-200 transition-all shadow-[0_0_15px_rgba(255,255,255,0.3)] mt-6">
                Save Paused Campaign
              </button>
            </form>
          </div>
        </div>

        {/* Right Side: Active Campaigns */}
        <div className="lg:col-span-8">
          <div className="glass-card p-6 min-h-[500px]">
            <h2 className="text-xs font-bold text-white uppercase tracking-widest border-b border-white/10 pb-3 mb-6">
              Saved Campaigns ({campaigns.length})
            </h2>

            {campaigns.length === 0 ? (
              <div className="h-64 flex items-center justify-center text-zinc-500 flex-col gap-4 opacity-50">
                <Sparkles className="h-10 w-10" />
                <p>No saved campaigns yet.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {campaigns.map(c => (
                  <div key={c.id} className={`p-5 rounded-xl border transition-all flex items-center justify-between ${c.active ? 'bg-white/5 border-white/20' : 'bg-transparent border-white/5 opacity-50'}`}>
                    
                    <div className="flex items-center gap-4">
                      <div className={`h-12 w-12 rounded-full flex items-center justify-center ${c.active ? 'bg-[#66fcf1]/20 text-[#66fcf1]' : 'bg-zinc-800 text-zinc-500'}`}>
                        <Bot className="h-6 w-6" />
                      </div>
                      
                      <div>
                        <h3 className="font-bold text-white text-lg flex items-center gap-2">
                          {c.name}<span className="text-[10px] rounded bg-amber-500/10 px-2 py-1 text-amber-300">Paused</span>
                        </h3>
                        <p className="text-zinc-400 text-sm">{c.niche} &bull; {c.preset}</p>
                      </div>
                    </div>

                    <div className="flex items-center gap-8">
                      <div className="text-right hidden sm:block">
                        <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest flex items-center gap-1 justify-end"><Clock className="h-3 w-3" /> Next Run</p>
                        <p className="text-sm text-zinc-300">
                          Paused; no next run
                        </p>
                      </div>

                      <div className="flex items-center gap-2">
                        <button type="button" onClick={() => handleToggle(c.id)} disabled title="Scheduling is disabled" className="p-3 rounded-lg border bg-white/5 border-white/10 text-zinc-500 cursor-not-allowed">
                          <Play className="h-5 w-5" />
                        </button>
                        <button 
                          onClick={() => handleDelete(c.id)} 
                          className="p-3 bg-red-500/10 border border-red-500/30 text-red-500 rounded-lg hover:bg-red-500/20 transition-all"
                        >
                          <Trash2 className="h-5 w-5" />
                        </button>
                      </div>
                    </div>

                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      {error && <p role="alert" className="mt-4 text-sm text-rose-300">{error}</p>}
    </div>
  );
}
