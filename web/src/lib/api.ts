export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn API failures into short, visible messages while retaining detail on the error. */
export async function apiRequest<T = unknown>(input: RequestInfo | URL, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = init?.timeoutMs ?? 60_000;
  const timer = setTimeout(() => controller.abort(new Error("Request timed out.")), timeoutMs);
  const onAbort = () => controller.abort(init?.signal?.reason);
  if (init?.signal?.aborted) onAbort();
  else init?.signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const { timeoutMs: _timeoutMs, ...requestInit } = init || {};
    const response = await fetch(input, { ...requestInit, signal: controller.signal });
    const body = await response.text();
    let data: unknown = null;
    if (body) {
      try {
        data = JSON.parse(body);
      } catch {
        data = body.slice(0, 500);
      }
    }
    if (!response.ok) {
      const record = data && typeof data === "object" ? data as Record<string, unknown> : null;
      const detail = record?.detail ?? record?.message ?? data;
      const message = typeof detail === "string" ? detail : `Request failed (${response.status})`;
      throw new ApiError(message.slice(0, 500), response.status);
    }
    return data as T;
  } catch (error) {
    if (controller.signal.aborted && !init?.signal?.aborted && !(error instanceof ApiError)) throw new Error("Request timed out. Please try again.");
    throw error;
  } finally {
    clearTimeout(timer);
    init?.signal?.removeEventListener("abort", onAbort);
  }
}

export function errorMessage(error: unknown, fallback = "The request could not be completed."): string {
  return error instanceof Error ? error.message.slice(0, 500) : fallback;
}

/** Use the current site's host and TLS for live job updates. */
export function websocketUrl(path: string): string {
  const url = new URL(path, window.location.origin);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
