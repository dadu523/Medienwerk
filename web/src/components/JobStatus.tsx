"use client";

import { AlertCircle, CheckCircle2, Loader2, PauseCircle, XCircle } from "lucide-react";
import type { JobLogEntry, JobSnapshot } from "@/lib/jobs";

const statusLabels: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_input: "Waiting for your selection",
  cancel_requested: "Stopping",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted by restart",
};

export function JobStatus({
  job,
  logs,
  error,
  connection,
  onClear,
}: {
  job: JobSnapshot | null;
  logs: JobLogEntry[];
  error?: string | null;
  connection?: "idle" | "connecting" | "connected" | "polling";
  onClear?: () => void;
}) {
  if (!job && !error) return null;
  const percent = job ? Math.round(job.progress * 100) : 0;
  const terminal = job && ["completed", "failed", "cancelled", "interrupted"].includes(job.status);
  const displayError = error || job?.error;
  const result = job?.result && typeof job.result === "object" ? job.result as Record<string, unknown> : null;
  const warnings = Array.isArray(result?.warnings) ? result.warnings.filter((item): item is string => typeof item === "string") : [];

  return (
    <section className="glass-card p-5 space-y-4" aria-live="polite">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {job?.status === "completed" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            : job?.status === "failed" || job?.status === "interrupted" ? <AlertCircle className="h-4 w-4 text-rose-400" />
              : job?.status === "cancelled" ? <XCircle className="h-4 w-4 text-zinc-400" />
              : job?.status === "awaiting_input" ? <PauseCircle className="h-4 w-4 text-amber-400" />
                : job?.status === "queued" || job?.status === "running" || job?.status === "cancel_requested" || !job ? <Loader2 className="h-4 w-4 animate-spin text-[var(--accent)]" /> : <CheckCircle2 className="h-4 w-4 text-zinc-400" />}
          <h2 className="text-xs font-bold uppercase tracking-widest text-white">
            {job ? statusLabels[job.status] || job.status : "Job status unavailable"}
          </h2>
        </div>
        {job && <span className="text-xs font-mono text-zinc-400">{percent}%</span>}
      </header>

      {job && (
        <>
          <div className="h-2 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className={`h-full transition-all duration-300 ${job.status === "failed" ? "bg-rose-500" : "bg-[var(--accent)]"}`}
              style={{ width: `${terminal && job.status === "completed" ? 100 : percent}%` }}
            />
          </div>
          <div className="flex items-center justify-between gap-3 text-xs text-zinc-400">
            <span className="truncate">{job.step || job.workflow || "Waiting for worker"}</span>
            {connection && !terminal && <span className="shrink-0">{connection === "connected" ? "Live" : connection === "polling" ? "Status polling" : "Connecting"}</span>}
          </div>
        </>
      )}

      {displayError && (
        <p className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-300">
          {displayError.slice(0, 500)}
        </p>
      )}

      {onClear && (terminal || displayError) && <button type="button" onClick={onClear} className="text-xs text-zinc-400 underline underline-offset-2">{terminal ? "Start a new job" : "Forget saved job and start a new one"}</button>}

      {warnings.length > 0 && <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-200"><p className="font-semibold">Output warnings</p><ul className="mt-1 list-disc pl-5">{warnings.slice(0, 8).map((warning, index) => <li key={`${index}:${warning}`}>{warning}</li>)}</ul></div>}

      {logs.length > 0 && (
        <div className="max-h-36 space-y-1 overflow-y-auto rounded-lg border border-white/5 bg-black/30 p-3">
          {logs.slice(-12).map((entry) => (
            <p key={`${entry.seq}:${entry.message}`} className="text-xs font-mono text-zinc-400">{entry.message}</p>
          ))}
        </div>
      )}
    </section>
  );
}
