"use client";

import { useEffect, useRef, useState } from "react";
import { apiRequest, errorMessage, websocketUrl } from "@/lib/api";

export type JobStatusName =
  | "queued" | "running" | "awaiting_input" | "cancel_requested"
  | "completed" | "failed" | "cancelled" | "interrupted";

export interface JobSnapshot {
  id: string;
  project_id?: string;
  workflow?: string;
  status: JobStatusName;
  progress: number;
  step?: string;
  result?: unknown;
  result_ids?: string[];
  result_media?: Array<{ id: string; url?: string; path?: string; [key: string]: unknown }>;
  error?: string | null;
  logs: string[];
  log_entries?: JobLogEntry[];
  latest_seq: number;
  [key: string]: unknown;
}

export interface JobLogEntry {
  seq: number;
  message: string;
  timestamp?: string;
}

export interface JobSubscription {
  job: JobSnapshot | null;
  logs: JobLogEntry[];
  browserFrame: string | null;
  error: string | null;
  connection: "idle" | "connecting" | "connected" | "polling";
}

const TERMINAL = new Set<JobStatusName>(["completed", "failed", "cancelled", "interrupted"]);
const MAX_LOGS = 250;
const MAX_RECONNECTS = 5;
const POLL_INTERVAL_MS = 8000;

function isTerminal(status?: string): status is JobStatusName {
  return Boolean(status && TERMINAL.has(status as JobStatusName));
}

function clampProgress(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(0, Math.min(1, numeric)) : 0;
}

function normalizeStatus(value: unknown): JobStatusName {
  const aliases: Record<string, JobStatusName> = {
    pending: "queued", processing: "running", success: "completed", succeeded: "completed",
  };
  const status = String(value || "queued");
  return aliases[status] || (TERMINAL.has(status as JobStatusName) || ["queued", "running", "awaiting_input", "cancel_requested"].includes(status)
    ? status as JobStatusName
    : "queued");
}

function logMessage(value: unknown): string | null {
  if (typeof value === "string") return value.slice(0, 1000);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const message = record.message ?? record.log ?? record.step;
    if (typeof message === "string") return message.slice(0, 1000);
  }
  return null;
}

function normalizeSnapshot(value: unknown): JobSnapshot {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const rawEntries = Array.isArray(record.log_entries) ? record.log_entries : [];
  const logEntries = rawEntries.flatMap((item) => {
    const entry = eventPayload(item);
    const message = logMessage(entry);
    return message ? [{ seq: Number(entry.seq) || 0, message, timestamp: typeof entry.timestamp === "string" ? entry.timestamp : undefined }] : [];
  }).slice(-MAX_LOGS);
  const rawLogs = Array.isArray(record.logs) ? record.logs : [];
  const logs = rawLogs.map(logMessage).filter((line): line is string => Boolean(line)).slice(-MAX_LOGS);
  return {
    ...record,
    id: String(record.id ?? record.job_id ?? ""),
    project_id: typeof record.project_id === "string" ? record.project_id : undefined,
    workflow: typeof record.workflow === "string" ? record.workflow : undefined,
    status: normalizeStatus(record.status),
    progress: clampProgress(record.progress),
    step: typeof record.step === "string" ? record.step : undefined,
    result: record.result,
    result_ids: Array.isArray(record.result_ids) ? record.result_ids.map(String) : [],
    result_media: Array.isArray(record.result_media) ? record.result_media as JobSnapshot["result_media"] : [],
    error: typeof record.error === "string" ? record.error : null,
    logs,
    log_entries: logEntries,
    latest_seq: Math.max(0, Number(record.latest_seq ?? record.seq ?? 0) || 0),
  };
}

function eventPayload(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

export function useJob(jobId: string | null | undefined): JobSubscription {
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const [logs, setLogs] = useState<JobLogEntry[]>([]);
  const [browserFrame, setBrowserFrame] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<JobSubscription["connection"]>("idle");

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setLogs([]);
      setBrowserFrame(null);
      setError(null);
      setConnection("idle");
      return;
    }

    let stopped = false;
    let terminal = false;
    let latestSeq = 0;
    let reconnects = 0;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    const controller = new AbortController();

    const stopLiveUpdates = () => {
      terminal = true;
      if (pollTimer) clearInterval(pollTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = null;
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
      socket = null;
    };

    const applySnapshot = (raw: unknown) => {
      if (stopped) return;
      const next = normalizeSnapshot(raw);
      if (next.latest_seq < latestSeq) return;
      if (terminal && !isTerminal(next.status)) return;
      latestSeq = Math.max(latestSeq, next.latest_seq);
      next.latest_seq = latestSeq;
      setJob(next);
      setError(null);
      setLogs((previous) => {
        const incoming = next.log_entries?.length ? next.log_entries : next.logs.map((message, index) => ({
          // Stable negative IDs keep legacy snapshot logs separate from sequenced events.
          seq: index - next.logs.length, message,
        }));
        const bySeq = new Map<number, JobLogEntry>();
        for (const entry of [...previous, ...incoming]) bySeq.set(entry.seq, entry);
        return [...bySeq.values()].sort((a, b) => a.seq - b.seq).slice(-MAX_LOGS);
      });
      if (isTerminal(next.status)) stopLiveUpdates();
    };

    const refresh = async () => {
      try {
        const snapshot = await apiRequest<unknown>(`/api/generate/status/${encodeURIComponent(jobId)}`, {
          cache: "no-store", signal: controller.signal,
        });
        applySnapshot(snapshot);
      } catch (fetchError) {
        if (!stopped && !controller.signal.aborted) setError(errorMessage(fetchError, "Could not read job status."));
      }
    };

    const appendLog = (seq: number, timestamp: string | undefined, data: unknown) => {
      const message = logMessage(data);
      if (!message) return;
      setLogs((previous) => {
        if (previous.some((entry) => entry.seq === seq)) return previous;
        return [...previous, { seq, message, timestamp }].sort((a, b) => a.seq - b.seq).slice(-MAX_LOGS);
      });
    };

    const receive = (raw: unknown) => {
      const envelope = eventPayload(raw);
      const type = String(envelope.type ?? "");
      const dataValue = envelope.data;
      if (type === "browser_frame") {
        const frame = typeof dataValue === "string" ? dataValue : logMessage(dataValue);
        if (frame && !stopped) setBrowserFrame(frame.replace(/^data:image\/[^;]+;base64,/, ""));
        return;
      }

      const seq = Math.max(0, Number(envelope.seq ?? 0) || 0);
      const timestamp = typeof envelope.timestamp === "string" ? envelope.timestamp : undefined;
      if (seq > 0 && seq <= latestSeq) return;
      if (seq > latestSeq + 1 && latestSeq > 0) void refresh();
      if (seq > 0) latestSeq = seq;

      if (type === "full_state") {
        applySnapshot(dataValue);
        return;
      }
      if (type === "log") {
        appendLog(seq || latestSeq, timestamp, dataValue);
        return;
      }

      const data = eventPayload(dataValue);
      if (type === "step") {
        setJob((previous) => {
          const base = previous ?? normalizeSnapshot({ id: jobId, status: "queued" });
          return normalizeSnapshot({
            ...base,
            progress: data.overall_progress ?? base.progress,
            step: data.title ?? base.step,
            latest_seq: Math.max(base.latest_seq, seq),
          });
        });
        return;
      }
      if (typeof data.message === "string" && (type === "step" || type === "update")) {
        appendLog(seq || latestSeq, timestamp, data.message);
      }
      setJob((previous) => {
        const base = previous ?? normalizeSnapshot({ id: jobId, status: "queued" });
        const merged = normalizeSnapshot({
          ...base,
          ...data,
          id: data.id ?? data.job_id ?? base.id,
          latest_seq: Math.max(base.latest_seq, seq),
        });
        if (isTerminal(base.status) && !isTerminal(merged.status)) return base;
        if (isTerminal(merged.status)) stopLiveUpdates();
        return merged;
      });
      if (data.error && typeof data.error === "string") setError(data.error.slice(0, 500));
      if (type === "status" && isTerminal(String(data.status))) void refresh();
    };

    const scheduleReconnect = () => {
      if (stopped || terminal || reconnectTimer) return;
      if (reconnects >= MAX_RECONNECTS) {
        setConnection("polling");
        return;
      }
      const delay = Math.min(1000 * 2 ** reconnects, 8000);
      reconnects += 1;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (stopped || terminal) return;
      setConnection("connecting");
      try {
        const nextSocket = new WebSocket(websocketUrl(`/api/generate/ws/${encodeURIComponent(jobId)}`));
        socket = nextSocket;
        nextSocket.onopen = () => {
          if (!stopped) setConnection("connected");
        };
        nextSocket.onmessage = (message) => {
          try {
            const payload = JSON.parse(message.data);
            receive(payload);
          } catch {
            if (typeof message.data === "string" && message.data.length < 2_000_000) {
              setBrowserFrame(message.data.replace(/^data:image\/[^;]+;base64,/, ""));
            } else setError("Received an unreadable job update.");
          }
        };
        nextSocket.onerror = () => {
          if (!stopped && !terminal) setConnection("polling");
        };
        nextSocket.onclose = () => {
          if (socket === nextSocket) socket = null;
          scheduleReconnect();
        };
      } catch {
        setConnection("polling");
        scheduleReconnect();
      }
    };

    setJob(null);
    setLogs([]);
    setBrowserFrame(null);
    setError(null);
    setConnection("connecting");
    void refresh();
    connect();
    pollTimer = setInterval(() => {
      if (!terminal) void refresh();
    }, POLL_INTERVAL_MS);

    return () => {
      stopped = true;
      controller.abort();
      if (pollTimer) clearInterval(pollTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket) socket.close();
      socket = null;
    };
  }, [jobId]);

  return { job, logs, browserFrame, error, connection };
}

export function useStartGuard() {
  const [starting, setStarting] = useState(false);
  const inFlight = useRef(false);
  const keyRef = useRef<string | null>(null);
  const run = async <T,>(request: (idempotencyKey: string) => Promise<T>): Promise<T | null> => {
    if (inFlight.current) return null;
    inFlight.current = true;
    setStarting(true);
    keyRef.current ??= globalThis.crypto.randomUUID();
    try {
      const result = await request(keyRef.current);
      keyRef.current = null;
      return result;
    } catch {
      // Keep the same key for a safe retry after an uncertain network outcome.
      return null;
    } finally {
      inFlight.current = false;
      setStarting(false);
    }
  };
  return { starting, run };
}

/** Restore a known job after navigation/reload without submitting any work. */
export function useResumableJobId(workflowKey: string): [string, (jobId: string) => void] {
  const [jobId, setJobId] = useState("");
  const [ready, setReady] = useState(false);
  const storageKey = `medienwerk.job.${workflowKey}`;
  useEffect(() => {
    try { setJobId(window.localStorage.getItem(storageKey) || ""); }
    catch { setJobId(""); }
    setReady(true);
  }, [storageKey]);
  useEffect(() => {
    if (!ready) return;
    try {
      if (jobId) window.localStorage.setItem(storageKey, jobId);
      else window.localStorage.removeItem(storageKey);
    } catch { /* Storage can be unavailable in private browsing; jobs still work in memory. */ }
  }, [jobId, ready, storageKey]);
  return [jobId, setJobId];
}

export function jobMediaUrl(job: JobSnapshot | null): string | null {
  if (!job) return null;
  const id = job.result_ids?.[0];
  if (id) return `/api/projects/media/${encodeURIComponent(id)}/download`;
  const result = job.result;
  const candidate = typeof result === "string"
    ? result
    : result && typeof result === "object"
      ? (result as Record<string, unknown>).path ?? (result as Record<string, unknown>).url
      : null;
  if (typeof candidate === "string" && candidate.startsWith("/api/")) return candidate;
  if (typeof candidate === "string" && candidate.length > 0) {
    return `/api/generate/media?path=${encodeURIComponent(candidate)}`;
  }
  const mediaUrl = job.result_media?.[0]?.url;
  return typeof mediaUrl === "string" ? mediaUrl : null;
}

export function createRequestKey(): string {
  return globalThis.crypto.randomUUID();
}
